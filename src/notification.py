import os
import telegram
import asyncio
from typing import Dict
import json
from pathlib import Path

class NotificationHandler:
    def __init__(self):
        self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')
        
        print(f"Initializing NotificationHandler:")
        print(f"Bot token exists: {bool(self.bot_token)}")
        print(f"Chat ID exists: {bool(self.chat_id)}")
        
        if not self.bot_token or not self.chat_id:
            print("WARNING: Missing Telegram credentials!")
            self.bot = None
        else:
            try:
                self.bot = telegram.Bot(token=self.bot_token)
                print("Successfully created Telegram bot instance")
            except Exception as e:
                print(f"Failed to create Telegram bot: {str(e)}")
                self.bot = None
                
        self.history_file = Path('opportunity_history.json')
        self.load_history()

    def load_history(self):
        """Load previously notified opportunities"""
        if self.history_file.exists():
            with open(self.history_file, 'r') as f:
                self.history = json.load(f)
        else:
            self.history = {}

    def save_history(self):
        """Save notified opportunities"""
        with open(self.history_file, 'w') as f:
            json.dump(self.history, f)

    def is_new_opportunity(self, opportunity: Dict) -> bool:
        """Check if this is a new opportunity worth notifying about"""
        key = f"{opportunity['symbol']}_{opportunity['direction']}"
        
        # If we've never seen this pair/direction, it's new
        if key not in self.history:
            return True
            
        last_spread = self.history[key]['spread']
        current_spread = opportunity['best_spread']
        
        # If the spread has improved by more than 0.5%, it's worth notifying
        if current_spread > last_spread + 0.5:
            return True
            
        return False

    async def send_notification(self, message: str):
        """Send a Telegram message"""
        if not self.bot:
            return
        
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='HTML'
            )
        except Exception as e:
            print(f"Failed to send notification: {str(e)}")

    def send_opportunity(self, opportunity: Dict):
        """Send and track a new arbitrage opportunity"""
        if not self.bot or not self.is_new_opportunity(opportunity):
            return
            
        message = (
            f"🔥 New Arbitrage Opportunity!\n\n"
            f"Symbol: {opportunity['symbol']}\n"
            f"Direction: {opportunity['direction']}\n"
            f"Spread: {opportunity['best_spread']}%\n"
            f"Executable Volume: {opportunity['executable_volume']} USDT\n"
            f"Networks: {', '.join(opportunity['supported_networks'])}\n\n"
            f"Prices:\n"
            f"Bitget: {opportunity['bitget_ask']}/{opportunity['bitget_bid']}\n"
            f"MEXC: {opportunity['mexc_ask']}/{opportunity['mexc_bid']}"
        )
        
        # Store in history
        key = f"{opportunity['symbol']}_{opportunity['direction']}"
        self.history[key] = {
            'spread': opportunity['best_spread'],
            'timestamp': str(datetime.now())
        }
        self.save_history()
        
        # Send notification
        asyncio.run(self.send_notification(message))
