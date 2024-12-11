import telegram
import asyncio
from typing import List, Dict

class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot = telegram.Bot(token=bot_token)
        self.chat_id = chat_id

    async def send_message(self, message: str):
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='HTML'
            )
        except Exception as e:
            logging.error(f"Telegram notification failed: {str(e)}")

    def format_opportunity(self, opp: Dict) -> str:
        return (
            f"<b>New Arbitrage Opportunity</b>\n\n"
            f"Symbol: {opp['symbol']}\n"
            f"Direction: {opp['direction']}\n"
            f"Spread: {opp['best_spread']}%\n"
            f"Executable Volume: {opp['executable_volume']} USDT\n"
            f"Networks: {', '.join(opp['supported_networks'])}\n\n"
            f"Bitget: {opp['bitget_ask']}/{opp['bitget_bid']}\n"
            f"MEXC: {opp['mexc_ask']}/{opp['mexc_bid']}\n"
        )

class EnhancedTrading:
    def __init__(self):
        self.logger = setup_logging()
        self.config = load_config()
        self.setup_exchanges()
        self.setup_notifier()
        self.token_info_cache = {}
        self.volume_threshold = 10000
        self.depth_threshold = 1000
        self.min_liquidity_score = 7
        self.min_spread_threshold = 0.5  # Minimum spread percentage to trigger notification
        
    def setup_notifier(self):
        try:
            bot_token = self.config['Telegram']['bot_token']
            chat_id = self.config['Telegram']['chat_id']
            self.notifier = TelegramNotifier(bot_token, chat_id)
            self.logger.info("Telegram notifier setup successful")
        except Exception as e:
            self.logger.error(f"Telegram notifier setup failed: {str(e)}")
            self.notifier = None

    async def notify_opportunities(self, opportunities: List[Dict]):
        if not self.notifier or not opportunities:
            return

        try:
            for opp in opportunities:
                if opp['best_spread'] >= self.min_spread_threshold:
                    message = self.notifier.format_opportunity(opp)
                    await self.notifier.send_message(message)
                    await asyncio.sleep(1)  # Avoid rate limiting
        except Exception as e:
            self.logger.error(f"Failed to send notifications: {str(e)}")

    def find_arbitrage_opportunities(self) -> None:
        try:
            self.logger.info("Starting arbitrage scan...")
            
            common_symbols = self.get_common_symbols()
            self.logger.info(f"Found {len(common_symbols)} verified common symbols")
            
            opportunities = []
            for symbol in common_symbols:
                result = self.calculate_arbitrage(symbol)
                if result and \
                   result['best_spread'] > 0 and \
                   result['min_liquidity_score'] >= self.min_liquidity_score and \
                   result['executable_volume'] >= self.depth_threshold:
                    opportunities.append(result)
                time.sleep(self.exchange1.rateLimit / 1000)
            
            opportunities.sort(key=lambda x: (
                x['best_spread'] * 
                x['min_liquidity_score'] * 
                min(1, x['executable_volume'] / self.depth_threshold)
            ), reverse=True)
            
            top_opportunities = opportunities[:5]
            
            # Save to CSV
            if top_opportunities:
                df = pd.DataFrame(top_opportunities)
                filename = f"arbitrage_opportunities_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                df.to_csv(filename, index=False)
                self.logger.info(f"Arbitrage opportunities saved to {filename}")
            
            # Send notifications
            asyncio.run(self.notify_opportunities(top_opportunities))
            
            # Log results
            self.logger.info("\nBest arbitrage opportunities:")
            for opp in top_opportunities:
                self.logger.info(
                    f"\nPair: {opp['symbol']}\n"
                    f"Direction: {opp['direction']}\n"
                    f"Spread: {opp['best_spread']}%\n"
                    f"Bitget: {opp['bitget_ask']}/{opp['bitget_bid']} "
                    f"(Depth: {opp['bitget_depth']} USDT, "
                    f"24h Volume: {opp['bitget_volume_24h']} USDT, "
                    f"Liquidity Score: {opp['bitget_liquidity_score']})\n"
                    f"MEXC: {opp['mexc_ask']}/{opp['mexc_bid']} "
                    f"(Depth: {opp['mexc_depth']} USDT, "
                    f"24h Volume: {opp['mexc_volume_24h']} USDT, "
                    f"Liquidity Score: {opp['mexc_liquidity_score']})\n"
                    f"Executable Volume: {opp['executable_volume']} USDT\n"
                    f"Supported Networks: {', '.join(opp['supported_networks'])}"
                )
            
        except Exception as e:
            self.logger.error(f"Error finding arbitrage opportunities: {str(e)}")

def main():
    try:
        trader = EnhancedTrading()
        trader.find_arbitrage_opportunities()
    except Exception as e:
        print(f"Program execution failed: {str(e)}")

if __name__ == "__main__":
    main()
