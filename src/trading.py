import ccxt
import time
import logging
import os
from pathlib import Path
import configparser
from typing import List, Dict, Tuple, Optional
import pandas as pd
from datetime import datetime
import numpy as np
import traceback
from .notification import NotificationHandler

def setup_logging():
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

def load_config():
    config = configparser.ConfigParser()
    config_path = 'config/config.ini'
    if not Path(config_path).exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    config.read(config_path)
    return config

class EnhancedTrading:
    def __init__(self):
        self.logger = setup_logging()
        self.config = load_config()
        self.setup_exchanges()
        self.token_info_cache = {}
        self.volume_threshold = 10000
        self.depth_threshold = 1000
        self.min_liquidity_score = 7
        self.notification_handler = NotificationHandler()
        
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
            'mexc_bid': 1.0,
            'min_liquidity_score': 8.0
        }
        self.notification_handler.send_opportunity(test_message)
        print("Test notification sent")

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
            print(f"{datetime.now()} - Exchange connections successful")
            
        except Exception as e:
            print(f"Failed to connect to exchanges: {str(e)}")
            raise

    def find_arbitrage_opportunities(self) -> None:
        try:
            print("Starting arbitrage search...")
            
            # For testing, use major pairs first
            symbols = ['BTC/USDT', 'ETH/USDT', 'XRP/USDT']
            
            opportunities = []
            for symbol in symbols:
                try:
                    # Get basic market data
                    orderbook1 = self.exchange1.fetch_order_book(symbol)
                    orderbook2 = self.exchange2.fetch_order_book(symbol)
                    
                    if orderbook1 and orderbook2:
                        bid1 = orderbook1['bids'][0][0] if orderbook1['bids'] else 0
                        ask1 = orderbook1['asks'][0][0] if orderbook1['asks'] else 0
                        bid2 = orderbook2['bids'][0][0] if orderbook2['bids'] else 0
                        ask2 = orderbook2['asks'][0][0] if orderbook2['asks'] else 0
                        
                        # Calculate spreads
                        spread1 = ((bid2 - ask1) / ask1) * 100  # Bitget → MEXC
                        spread2 = ((bid1 - ask2) / ask2) * 100  # MEXC → Bitget
                        
                        best_spread = max(spread1, spread2)
                        
                        if best_spread > 0.5:  # Only notify for >0.5% spread
                            opp = {
                                'symbol': symbol,
                                'direction': 'Bitget→MEXC' if spread1 > spread2 else 'MEXC→Bitget',
                                'best_spread': round(best_spread, 3),
                                'executable_volume': min(
                                    orderbook1['bids'][0][1] * bid1,
                                    orderbook2['asks'][0][1] * ask2
                                ),
                                'supported_networks': ['ETH', 'BSC'],  # Example
                                'bitget_ask': ask1,
                                'bitget_bid': bid1,
                                'mexc_ask': ask2,
                                'mexc_bid': bid2,
                                'min_liquidity_score': 8.0  # Example
                            }
                            opportunities.append(opp)
                            self.notification_handler.send_opportunity(opp)
                    
                    time.sleep(1)  # Rate limiting
                    
                except Exception as e:
                    print(f"Error processing {symbol}: {str(e)}")
                    continue
                
            if opportunities:
                print(f"Found {len(opportunities)} opportunities")
            else:
                print("No profitable opportunities found")
                
        except Exception as e:
            print(f"Error in arbitrage search: {str(e)}")
            traceback.print_exc()
