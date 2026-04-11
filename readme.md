# Telegram Bot

A Telegram bot for managing attack requests with admin approval system, MongoDB database, and external API integration.

## Features

- 🔐 User approval system with expiration dates
- 👑 Admin commands for user management
- 📊 Attack statistics and logging
- 🚫 Blocked ports validation
- 💾 MongoDB database for persistent storage
- 🔄 24/7 deployment ready (Railway, Heroku, etc.)

## Prerequisites

- Python 3.11 or higher
- MongoDB database (Atlas or local)
- Telegram Bot Token (from @BotFather)
- External API endpoint with authentication key

## Environment Variables Setup

Create a `.env` file in the root directory with the following variables:

```env
MONGO_URI=your_mongo_url
TELEGRAM_BOT_TOKEN=your_bot_token
ADMIN_USER_ID=your_telegram_id
API_KEY=your_api_key
BASE_URL=your_api_url
ATTACK_MODE=api