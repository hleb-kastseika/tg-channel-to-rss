# tg-channel-to-rss

AWS Lambda function for converting a **public Telegram channel** into an **RSS feed**.

## How it works
1. The Lambda receives requests via API Gateway:  
   `GET /feed/{channel_name}?key={api_key}`  
2. It fetches the public static view of the channel at  
   `https://t.me/s/{channel_name}`.  
3. Using **BeautifulSoup**, it parses each Telegram message bubble, extracts:
   - Post text (with links preserved),
   - Photo previews and link-preview images,  
   - Publication time and post URL.  
4. The extracted data is converted into an RSS feed with [rfeed](https://pypi.org/project/rfeed/), returning valid XML to the caller.

⚠ **Limitations**  
- Telegram **does not guarantee** that all public channels expose their posts on `t.me/s/…`.  
- Channels flagged as **sensitive**, geo-restricted, or with **content protection** enabled may show a blank page or limited content even though they are public in the Telegram app.  
- There is no workaround other than viewing those channels within Telegram or using the official Bot API.

## Requirements
- Python 3.13 or higher  
- AWS SAM (Serverless Application Model)

## Build and deploy
1. Set your API key: edit `samconfig.yaml` or pass `--parameter-overrides ApiKey=YOUR_KEY`.  
2. Build and deploy:
```bash
sam build
sam deploy --guided
```

## Usage
Call the endpoint with the channel name and your API key:
```bash
curl 'https://<api-gateway-url>/feed/cool_telegram_channel?key=test'
```
This returns an RSS XML feed of the channel’s recent posts, including text and photo previews, ready to import into your RSS reader.
