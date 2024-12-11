import ccxt
import time
import logging
import os
import traceback
from pathlib import Path
import configparser
from typing import List, Dict, Tuple, Optional
import pandas as pd
from datetime import datetime
import numpy as np
from .notification import NotificationHandler

def load_config():
    """Load configuration from config file"""
    config = configparser.ConfigParser()
    config_path = 'config/config.ini'
    if not Path(config_path).exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    config.read(config_path)
    return config

def setup_logging():
    """Setup logging configuration"""
    Path("logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(message)s',
        handlers=[
            logging.FileHandler("logs/trading.log"),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

class EnhancedTrading:
    def setup_exchanges(self):
        """Setup exchange connections"""
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
            self.logger.info("Exchange connections successful")
            
        except Exception as e:
            self.logger.error(f"Failed to connect to exchanges: {str(e)}")
            raise

    def __init__(self):
        self.logger = setup_logging()
        print("Starting program...")
        print("Checking environment variables:")
        print(f"Telegram Bot Token exists: {'TELEGRAM_BOT_TOKEN' in os.environ}")
        print(f"Telegram Chat ID exists: {'TELEGRAM_CHAT_ID' in os.environ}")
        
        # Load config and check its contents
        self.config = load_config()
        print("Config file exists, contents:")
        if Path('config/config.ini').exists():
            with open('config/config.ini', 'r') as f:
                print(f.read())
        
        self.setup_exchanges()
        self.token_info_cache = {}
        self.volume_threshold = 10000  # Minimum 24h volume (USDT)
        self.depth_threshold = 1000    # Minimum order depth (USDT)
        self.min_liquidity_score = 7   # Minimum liquidity score (1-10)
        self.notification_handler = NotificationHandler()
        
        # Send test notification
        print("Sending test notification...")
        test_message = {
            'symbol': 'TEST/USDT',
            'direction': 'Test',
            'best_spread': 1.0,
            'executable_volume': 1000,
            'supported_networks': ['TEST'],
            'bitget_ask': 1.0,
            'bitget_bid': 1.0,
            'mexc_ask': 1.0,
            'mexc_bid': 1.0
        }
        self.notification_handler.send_opportunity(test_message)
        print("Test notification sent")

        def get_token_info(self, exchange: ccxt.Exchange, symbol: str) -> Optional[Dict]:
        """Get token details including contract address and supported networks"""
        try:
            # Check cache first
            cache_key = f"{exchange.id}_{symbol}"
            if cache_key in self.token_info_cache:
                return self.token_info_cache[cache_key]
            
            market = exchange.markets.get(symbol)
            if not market:
                return None
                
            base = market['base']
            quote = market['quote']
            
            currencies = exchange.fetch_currencies()
            if base not in currencies:
                return None
                
            currency_info = currencies[base]
            
            networks = {}
            contract_addresses = {}
            
            if 'networks' in currency_info:
                for network, info in currency_info['networks'].items():
                    networks[network] = {
                        'network': network,
                        'contract': info.get('contract'),
                        'withdrawEnabled': info.get('withdraw', True),
                        'depositEnabled': info.get('deposit', True),
                        'withdrawFee': info.get('withdrawFee', 0),
                        'minWithdraw': info.get('withdrawMin', 0)
                    }
                    if info.get('contract'):
                        contract_addresses[network] = info['contract'].lower()
            
            token_info = {
                'symbol': base,
                'quote': quote,
                'active': market['active'],
                'base': base,
                'networks': networks,
                'contract_addresses': contract_addresses,
                'precision': market['precision'],
                'limits': market['limits'],
                'exchange': exchange.id
            }
            
            self.token_info_cache[cache_key] = token_info
            return token_info
            
        except Exception as e:
            self.logger.error(f"Error getting token info for {symbol} on {exchange.id}: {str(e)}")
            return None

    def get_market_data(self, exchange: ccxt.Exchange, symbol: str) -> Tuple[Dict, Dict, float]:
        """Get market data including orderbook, ticker, and liquidity score"""
        try:
            orderbook = exchange.fetch_order_book(symbol, 20)
            ticker = exchange.fetch_ticker(symbol)
            
            # Calculate simple liquidity score based on volume
            liquidity_score = min(10, (ticker.get('quoteVolume', 0) / self.volume_threshold) * 5)
            
            return orderbook, ticker, liquidity_score
            
        except Exception as e:
            self.logger.error(f"Failed to get market data for {symbol} on {exchange.id}: {str(e)}")
            return None, None, 0

    def find_arbitrage_opportunities(self) -> None:
        """Find and notify about arbitrage opportunities"""
        try:
            self.logger.info("Starting arbitrage search...")
            
            # Get some common USDT pairs for testing
            symbols = ['BTC/USDT', 'ETH/USDT', 'XRP/USDT']  # Starting with major pairs
            
            opportunities = []
            for symbol in symbols:
                try:
                    # Get market data from both exchanges
                    orderbook1, ticker1, liquidity1 = self.get_market_data(self.exchange1, symbol)
                    orderbook2, ticker2, liquidity2 = self.get_market_data(self.exchange2, symbol)
                    
                    if all([orderbook1, orderbook2, ticker1, ticker2]):
                        # Simple spread calculation
                        bid1 = orderbook1['bids'][0][0] if orderbook1['bids'] else 0
                        ask1 = orderbook1['asks'][0][0] if orderbook1['asks'] else 0
                        bid2 = orderbook2['bids'][0][0] if orderbook2['bids'] else 0
                        ask2 = orderbook2['asks'][0][0] if orderbook2['asks'] else 0
                        
                        # Calculate spreads
                        spread1 = ((bid2 - ask1) / ask1) * 100  # Bitget → MEXC
                        spread2 = ((bid1 - ask2) / ask2) * 100  # MEXC → Bitget
                        
                        best_spread = max(spread1, spread2)
                        if best_spread > 0:
                            opp = {
                                'symbol': symbol,
                                'direction': 'Bitget→MEXC' if spread1 > spread2 else 'MEXC→Bitget',
                                'best_spread': best_spread,
                                'executable_volume': min(
                                    orderbook1['bids'][0][1] if orderbook1['bids'] else 0,
                                    orderbook2['asks'][0][1] if orderbook2['asks'] else 0
                                ) * ask1,
                                'supported_networks': ['ETH', 'BSC'],  # Simplified for testing
                                'bitget_ask': ask1,
                                'bitget_bid': bid1,
                                'mexc_ask': ask2,
                                'mexc_bid': bid2
                            }
                            opportunities.append(opp)
                            
                            # Send notification for good opportunities
                            if best_spread >= 0.5:  # 0.5% minimum spread
                                self.notification_handler.send_opportunity(opp)
                    
                    time.sleep(exchange.rateLimit / 1000)
                    
                except Exception as e:
                    self.logger.error(f"Error processing {symbol}: {str(e)}")
                    continue
            
            if opportunities:
                self.logger.info(f"Found {len(opportunities)} opportunities")
            else:
                self.logger.info("No profitable opportunities found")
                
        except Exception as e:
            self.logger.error(f"Error in arbitrage search: {str(e)}")
            raise

def main():
    try:
        trader = EnhancedTrading()
        trader.find_arbitrage_opportunities()
    except Exception as e:
        print(f"Program execution failed: {str(e)}")
        traceback.print_exc()

if __name__ == "__main__":
    main()
