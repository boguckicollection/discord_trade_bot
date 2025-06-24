# Discord Trade Bot

Simple Discord bot to handle auctions via forum threads.

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Set environment variables:
   - `DISCORD_TOKEN` - your bot token.
   - `FORUM_CHANNEL_ID` - ID of the forum channel for auctions.
   - `HTML_EXPORT_DIR` - directory where auction HTML files will be saved (default `exports`).
   - `AUCTION_ITEMS_FILE` - CSV file with predefined auction items (default `auction_items.csv`).

3. Run the bot:
   ```bash
   python bot.py
   ```

## Predefined auction items

Create `auction_items.csv` with columns `title,description,start_price,increment,duration`.
You can start the next item from the file using the command:

```bash
!start_next
```

Each auction is exported to an HTML file that can be added as a browser source in OBS.
