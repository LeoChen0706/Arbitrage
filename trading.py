import ccxt
import time
import logging
from pathlib import Path
import configparser
from typing import List, Dict, Tuple, Optional
import pandas as pd
from datetime import datetime
import numpy as np
import telegram
import asyncio
import os

def setup_logging():
    """Setup logging configuration"""
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("logs/trading.log"),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

def load_config():
    """Load configuration from config.ini file"""
    config = configparser.ConfigParser()
    config_path = 'config/config.ini'
    if not Path(config_path).exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    config.read(config_path)
    return config

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
        self.min_spread_threshold = 0.5

    def setup_exchanges(self):
        try:
            bitget_config = {
                'apiKey': self.config['Bitget']['api_key'],
                'secret': self.config['Bitget']['secret_key'],
                'password': self.config['Bitget'].get('passphrase', ''),
                'enableRateLimit': True,
                'options': {'defaultType': 'spot'}
            }
            self.exchange1 = ccxt.bitget(bitget_config)
            
            mexc_config = {
                'apiKey': self.config['MEXC']['api_key'],
                'secret': self.config['MEXC']['secret_key'],
                'enableRateLimit': True,
                'options': {'defaultType': 'spot'}
            }
            self.exchange2 = ccxt.mexc(mexc_config)
            
            self.exchange1.load_markets()
            self.exchange2.load_markets()
            self.logger.info("Exchanges connected successfully")
            
        except Exception as e:
            self.logger.error(f"Exchange connection failed: {str(e)}")
            raise

    def setup_notifier(self):
        try:
            bot_token = self.config['Telegram']['bot_token']
            chat_id = self.config['Telegram']['chat_id']
            self.notifier = TelegramNotifier(bot_token, chat_id)
            self.logger.info("Telegram notifier setup successful")
        except Exception as e:
            self.logger.error(f"Telegram notifier setup failed: {str(e)}")
            self.notifier = None

    def get_common_symbols(self) -> List[str]:
        """Get list of common trading pairs between exchanges"""
        try:
            # Get USDT trading pairs from both exchanges
            bitget_symbols = set(symbol for symbol in self.exchange1.symbols 
                               if symbol.endswith('/USDT'))
            mexc_symbols = set(symbol for symbol in self.exchange2.symbols 
                             if symbol.endswith('/USDT'))
            
            # Find common symbols
            common_symbols = bitget_symbols.intersection(mexc_symbols)
            self.logger.info(f"Found {len(common_symbols)} common symbols")
            
            # Verify each symbol
            verified_symbols = []
            for symbol in common_symbols:
                try:
                    # Get 24h ticker data for volume verification
                    ticker1 = self.exchange1.fetch_ticker(symbol)
                    ticker2 = self.exchange2.fetch_ticker(symbol)
                    
                    # Check if 24h volume meets threshold
                    if (ticker1.get('quoteVolume', 0) >= self.volume_threshold and 
                        ticker2.get('quoteVolume', 0) >= self.volume_threshold):
                        verified_symbols.append(symbol)
                        self.logger.debug(f"Verified symbol: {symbol}")
                    else:
                        self.logger.debug(f"Insufficient volume for {symbol}")
                    
                    # Respect rate limits
                    time.sleep(self.exchange1.rateLimit / 1000)
                    
                except Exception as e:
                    self.logger.warning(f"Error verifying symbol {symbol}: {str(e)}")
                    continue
            
            self.logger.info(f"Verified {len(verified_symbols)} symbols")
            return verified_symbols
            
        except Exception as e:
            self.logger.error(f"Error getting common symbols: {str(e)}")
            return []

    def get_market_data(self, exchange: ccxt.Exchange, symbol: str) -> Tuple[Dict, Dict, float]:
        """Get market data including orderbook and ticker"""
        try:
            orderbook = exchange.fetch_order_book(symbol, 20)
            ticker = exchange.fetch_ticker(symbol)
            
            # Calculate average prices and depth
            bids_volume = sum(bid[1] for bid in orderbook['bids'][:20])
            asks_volume = sum(ask[1] for ask in orderbook['asks'][:20])
            depth = min(bids_volume, asks_volume)
            
            # Calculate liquidity score (1-10)
            volume_24h = ticker.get('quoteVolume', 0)
            volume_score = min(5, (volume_24h / self.volume_threshold) * 2.5)
            depth_score = min(5, (depth / self.depth_threshold) * 2.5)
            liquidity_score = volume_score + depth_score
            
            return orderbook, ticker, liquidity_score
            
        except Exception as e:
            self.logger.error(f"Error getting market data for {symbol}: {str(e)}")
            return None, None, 0

    def calculate_arbitrage(self, symbol: str) -> Optional[Dict]:
        """Calculate arbitrage opportunity for a symbol"""
        try:
            # Get market data from both exchanges
            orderbook1, ticker1, liquidity1 = self.get_market_data(self.exchange1, symbol)
            orderbook2, ticker2, liquidity2 = self.get_market_data(self.exchange2, symbol)
            
            if not all([orderbook1, orderbook2, ticker1, ticker2]):
                return None
            
            # Get best bid/ask prices
            bid1 = orderbook1['bids'][0][0] if orderbook1['bids'] else 0
            ask1 = orderbook1['asks'][0][0] if orderbook1['asks'] else 0
            bid2 = orderbook2['bids'][0][0] if orderbook2['bids'] else 0
            ask2 = orderbook2['asks'][0][0] if orderbook2['asks'] else 0
            
            # Calculate spreads
            spread1 = ((bid2 - ask1) / ask1) * 100  # Bitget → MEXC
            spread2 = ((bid1 - ask2) / ask2) * 100  # MEXC → Bitget
            
            # Calculate executable volume
            volume1 = sum(bid[1] for bid in orderbook1['bids'][:5])
            volume2 = sum(ask[1] for ask in orderbook2['asks'][:5])
            executable_volume = min(volume1, volume2)
            
            return {
                'symbol': symbol,
                'bitget_bid': bid1,
                'bitget_ask': ask1,
                'mexc_bid': bid2,
                'mexc_ask': ask2,
                'spread1': spread1,
                'spread2': spread2,
                'best_spread': max(spread1, spread2),
                'direction': 'Bitget→MEXC' if spread1 > spread2 else 'MEXC→Bitget',
                'supported_networks': ['BEP20', 'ERC20'],  # Default networks
                'bitget_depth': volume1,
                'mexc_depth': volume2,
                'bitget_volume_24h': ticker1.get('quoteVolume', 0),
                'mexc_volume_24h': ticker2.get('quoteVolume', 0),
                'bitget_liquidity_score': liquidity1,
                'mexc_liquidity_score': liquidity2,
                'min_liquidity_score': min(liquidity1, liquidity2),
                'executable_volume': executable_volume
            }
            
        except Exception as e:
            self.logger.error(f"Error calculating arbitrage for {symbol}: {str(e)}")
            return None

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
