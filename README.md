# tg-channel-to-rss

AWS Lambda function for converting of Telegram channel to RSS feed.

## Requirements

 - Python 3.9 or higher
 - AWS SAM

## How to build and deploy

1. Override 'ApiKey' parameter in 'samconfig.yaml' or through command arguments.

2. Run SAM:
```bash
sam build
sam deploy --guided
```

## How to use

Pass Telegram channel name as path parameter and api key as query parameter:
```
GET {api-gateway-url}/feed/{channel_name}?key={api_key}
```
For example:
```bash
curl 'https://rotg43azo4.execute-api.eu-west-1.amazonaws.com/Prod/feed/cool_telegram_channel?key=test'
```
It will return the XML file.