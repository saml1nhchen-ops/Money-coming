"""Use Crawl4AI's actual HTTP strategy; no browser session, no fallback engine."""
import asyncio,json,pathlib,sys
from crawl4ai import AsyncWebCrawler,CrawlerRunConfig
from crawl4ai.async_crawler_strategy import AsyncHTTPCrawlerStrategy
from crawl4ai.async_configs import HTTPCrawlerConfig
async def main():
 url,out=sys.argv[1:];dest=pathlib.Path(out)
 async with AsyncWebCrawler(crawler_strategy=AsyncHTTPCrawlerStrategy(browser_config=HTTPCrawlerConfig(method='GET'))) as crawler:
  result=await crawler.arun(url=url,config=CrawlerRunConfig())
  (dest/'page.html').write_text(result.html or '',encoding='utf-8')
  (dest/'page.md').write_text(str(result.markdown or ''),encoding='utf-8')
  (dest/'crawl-result.json').write_text(result.model_dump_json(indent=2),encoding='utf-8')
  print(json.dumps({'success':result.success,'status_code':result.status_code,'url':result.url,'error':result.error_message},ensure_ascii=False))
  if not result.success:raise SystemExit(1)
asyncio.run(main())
