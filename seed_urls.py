import asyncio
import storage

async def seed():
    await storage.init_db()
    
    popular_urls = [
        "https://www.khmertimeskh.com",
        "https://phnompenhpost.com",
        "https://cambodianess.com",
        "https://eacnews.asia",
        "https://www.freshnewsasia.com",
        "https://thmeythmey.com",
        "https://kohsantepheapdaily.com.kh",
        "https://kampucheathmey.com"
    ]
    
    for url in popular_urls:
        print(f"Adding {url}...")
        await storage.add_base_url(url)
        
    print("Done!")

if __name__ == '__main__':
    asyncio.run(seed())
