import asyncio
import json
import os
import re
import requests
import datetime
from playwright.async_api import async_playwright

# ==========================================
# 【LINE設定】
# ==========================================
LINE_CHANNEL_ACCESS_TOKEN = "lsKSkgVlb2TM/F7ZiGj8zWnL7vTNgG97CQZtaPcYCf7sgu52jcUn1UJTrF2ZXh/0LRU4w/JS0AVxDJi5ClwnhJfHdXdEQYIn7VM+LsY0po6Q9l9DSJR3IeSx0otvxg0FHvumC/hULbQhPQRPb6yIPAdB04t89/1O/w1cDnyilFU="
USER_ID = "Ud902b5e32d302a9854e056357a282a4c"

# チェック間隔（分）
INTERVAL_MINUTES = 3

TARGET_LIST = [
    {
        "brand_name": "マリテフランソワジルボー",
        "url": "https://jp.mercari.com/search?brand_id=4563&sort=created_time&price_max=5000&order=desc&status=on_sale&category_id=32"
    },
    {
        "brand_name": "Supreme",
        "url": "https://jp.mercari.com/search?keyword=supreme&category_id=30&order=desc&price_max=6000&sort=created_time&status=on_sale"
    },
    {
        "brand_name": "Stussy",
        "url": "https://jp.mercari.com/search?keyword=stussy&sort=created_time&order=desc&category_id=30&status=on_sale&price_max=4000"
    }
]

NOTIFIED_FILE = "notified_items.txt"

def clean_header_value(val):
    if not val:
        return ""
    return re.sub(r'[^a-zA-Z0-9\-_.~+/=]', '', str(val))

def load_notified_items():
    if os.path.exists(NOTIFIED_FILE):
        with open(NOTIFIED_FILE, "r", encoding="utf-8") as f:
            return set(f.read().splitlines())
    return set()

def save_notified_items(notified_set):
    with open(NOTIFIED_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(notified_set))

def send_line_notify(brand_label, item_name, price_num, item_url, market_info):
    url = "https://api.line.me/v2/bot/message/push"
    clean_token = clean_header_value(LINE_CHANNEL_ACCESS_TOKEN)
    clean_user_id = clean_header_value(USER_ID)
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {clean_token}"
    }
    
    price_str = f"¥{price_num:,}" if isinstance(price_num, int) else str(price_num)
    
    text_message = f"🚨 【新着通知】{brand_label}\n\n"
    text_message += f"【商品名】\n{item_name}\n\n"
    text_message += f"【出品価格】\n{price_str}\n\n"
    text_message += f"📊 【売り切れ相場データ】\n{market_info}\n\n"
    text_message += f"【商品URL】\n{item_url}"
    
    payload = {
        "to": clean_user_id,
        "messages": [{"type": "text", "text": text_message}]
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            print(f"✅ 【LINE通知成功】[{brand_label}] {item_name} ({price_str})")
        else:
            print(f"❌ LINE通知エラー: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"送信エラー: {e}")

def extract_search_keywords(brand_name, item_name):
    cleaned = re.sub(r'【.*?】|\[.*?\]|\(.*?\)|\（.*?\）', ' ', item_name)
    cleaned = re.sub(r'[★☆✨◆◇■□▼▽◎▲△!！?？/／_・\-]', ' ', cleaned)
    
    remove_words = [
        'MARITHE', 'FRANCOIS', 'GIRBAUD', 'マリテフランソワジルボー', 'ジルボー',
        'SUPREME', 'シュプリーム',
        'STUSSY', 'ステューシー',
        '美品', '新品', '未使用', '極美品', '即購入OK', '送料込み', '送料無料', 
        '中古', '古着', 'メンズ', 'レディース', 'キッズ', 'サイズ', 'L', 'M', 'S', 'XL'
    ]
    
    words = cleaned.split()
    item_specific_words = [w for w in words if w.upper() not in remove_words and len(w) > 1]
    
    if item_specific_words:
        kw = f"{brand_name} " + " ".join(item_specific_words[:2])
    else:
        kw = brand_name
        
    return kw

async def fetch_mercari_items(page, url):
    try:
        async with page.expect_response(
            lambda response: "entities:search" in response.url and response.status == 200,
            timeout=30000
        ) as response_info:
            await page.goto(url, wait_until="domcontentloaded")
            await page.mouse.wheel(0, 300)
        
        response = await response_info.value
        data = await response.json()
        return data.get("items", [])
    except Exception as e:
        print(f"⚠️ 通信取得エラー ({url}): {e}")
        return []

async def get_market_price(context, brand_name, item_name, current_price):
    if not item_name or item_name == "商品名不明":
        return "・商品名が取得できませんでした。"

    search_kw = extract_search_keywords(brand_name, item_name)
    sold_url = f"https://jp.mercari.com/search?keyword={requests.utils.quote(search_kw)}&status=sold_out&sort=created_time&order=desc"
    
    search_page = await context.new_page()
    sold_items_data = await fetch_mercari_items(search_page, sold_url)
    await search_page.close()

    sold_prices = [int(item.get('price', 0)) for item in sold_items_data if int(item.get('price', 0)) > 300]

    if sold_prices:
        avg_price = sum(sold_prices) // len(sold_prices)
        info = f"・検索ワード: 「{search_kw}」\n"
        info += f"・直近の平均売価: 約 {avg_price:,}円 ({len(sold_prices)}件対象)"
        if current_price:
            diff = avg_price - current_price
            if diff > 0:
                info += f"\n👉 相場より約 {diff:,}円 安く出品されています！"
            else:
                info += f"\n👉 相場と同等かやや高めです。"
        return info
    else:
        return f"・キーワード「{search_kw}」での売り切れデータは見つかりませんでした。"

async def check_once(context, notified_set):
    total_new = 0
    for target in TARGET_LIST:
        brand_name = target["brand_name"]
        url = target["url"]
        
        page = await context.new_page()
        fetched_items = await fetch_mercari_items(page, url)
        await page.close()

        for item in fetched_items[:3]:
            item_id = item.get('id')
            if not item_id or item_id in notified_set:
                continue
            
            name = item.get('name', '商品名不明')
            price = int(item.get('price', 0))
            item_url = f"https://jp.mercari.com/item/{item_id}"
            
            print(f"✨ 新着検出 [{brand_name}]: {name} ({price}円)")
            market_info = await get_market_price(context, brand_name, name, price)
            
            send_line_notify(brand_name, name, price, item_url, market_info)
            
            notified_set.add(item_id)
            total_new += 1
            await asyncio.sleep(1)

    save_notified_items(notified_set)
    return total_new

async def main():
    notified_set = load_notified_items()
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        
        print(f"🚀 監視スタート（{INTERVAL_MINUTES}分ごとに自動チェックします）")
        
        count = 1
        while True:
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{now_str}] 🔍 回数 #{count} - 監視中...")
            
            new_cnt = await check_once(context, notified_set)
            print(f"   └ 今回の検出: {new_cnt} 件")
            
            count += 1
            await asyncio.sleep(INTERVAL_MINUTES * 60)

if __name__ == "__main__":
    asyncio.run(main())
