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
        self.verified_networks = {}
        self.volume_threshold = 10000  # Minimum 24h volume (USDT)
        self.depth_threshold = 1000    # Minimum order depth (USDT)
        self.min_liquidity_score = 7   # Minimum liquidity score (1-10)
        self.min_spread_threshold = 0.5 # Minimum spread percentage
        
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

    def normalize_network_name(self, network: str) -> str:
        """Normalize network names across exchanges"""
        network = network.upper()
        network_mappings = {
            'BSC': 'BEP20',
            'BINANCESMARTCHAIN': 'BEP20',
            'SMARTCHAIN': 'BEP20',
            'ETH': 'ERC20',
            'ETHEREUM': 'ERC20',
            'MATIC': 'POLYGON',
            'POLYGON': 'POLYGON',
            'TRX': 'TRC20',
            'TRON': 'TRC20',
        }
        return network_mappings.get(network, network)

    def get_token_info(self, exchange: ccxt.Exchange, symbol: str) -> Optional[Dict]:
        """Get detailed token information including contract addresses"""
        try:
            cache_key = f"{exchange.id}_{symbol}"
            if cache_key in self.token_info_cache:
                return self.token_info_cache[cache_key]
            
            # Parse trading pair
            market = exchange.markets.get(symbol)
            if not market:
                return None
                
            base = market['base']
            
            # Get currency information
            currencies = exchange.fetch_currencies()
            if base not in currencies:
                return None
                
            currency_info = currencies[base]
            token_info = {'contracts': {}, 'networks': set()}
            
            # Handle Bitget's structure
            if exchange.id == 'bitget':
                if 'info' in currency_info and isinstance(currency_info['info'], dict):
                    chains = currency_info['info'].get('chains', [])
                    if isinstance(chains, list):
                        for chain in chains:
                            if isinstance(chain, dict):
                                network = chain.get('chainName', '').upper()
                                contract = chain.get('contractAddress')
                                withdraw_enabled = chain.get('withdrawEnable', True)
                                deposit_enabled = chain.get('depositEnable', True)
                                
                                if network and contract:
                                    network = self.normalize_network_name(network)
                                    token_info['contracts'][network] = contract.lower()
                                    if withdraw_enabled and deposit_enabled:
                                        token_info['networks'].add(network)
                                        self.logger.info(f"Found Bitget contract for {symbol} on {network}: {contract}")
            
            # Handle MEXC's structure
            elif exchange.id == 'mexc':
                if 'info' in currency_info:
                    for network_info in currency_info.get('networkList', []):
                        if isinstance(network_info, dict):
                            network = network_info.get('network', '').upper()
                            contract = network_info.get('contractAddress')
                            withdraw_enabled = network_info.get('withdrawEnable', True)
                            deposit_enabled = network_info.get('depositEnable', True)
                            
                            if network and contract:
                                network = self.normalize_network_name(network)
                                token_info['contracts'][network] = contract.lower()
                                if withdraw_enabled and deposit_enabled:
                                    token_info['networks'].add(network)
                                    self.logger.info(f"Found MEXC contract for {symbol} on {network}: {contract}")
            
            if not token_info['networks']:
                self.logger.debug(f"No networks found for {symbol} on {exchange.id}")
            
            self.token_info_cache[cache_key] = token_info
            return token_info
            
        except Exception as e:
            self.logger.error(f"Error getting token info for {symbol} on {exchange.id}: {str(e)}")
            return None

    def verify_token_contracts(self, symbol: str) -> Tuple[bool, List[str]]:
        """Verify token contracts match across exchanges and return compatible networks"""
        try:
            token1 = self.get_token_info(self.exchange1, symbol)
            token2 = self.get_token_info(self.exchange2, symbol)

            if not token1 or not token2:
                self.logger.debug(f"Could not get token info for {symbol}")
                return False, []

            # Find networks with matching contracts
            verified_networks = []
            for network in token1['networks'] & token2['networks']:
                contract1 = token1['contracts'].get(network)
                contract2 = token2['contracts'].get(network)
                
                if contract1 and contract2:
                    if contract1.lower() == contract2.lower():
                        verified_networks.append(network)
                        self.logger.info(
                            f"Verified {symbol} on {network}\n"
                            f"Contract: {contract1.lower()}"
                        )
                    else:
                        self.logger.warning(
                            f"Contract mismatch for {symbol} on {network}:\n"
                            f"Bitget: {contract1}\n"
                            f"MEXC: {contract2}"
                        )

            if verified_networks:
                return True, verified_networks
            return False, []

        except Exception as e:
            self.logger.error(f"Error verifying token contracts for {symbol}: {str(e)}")
            return False, []

    def get_common_symbols(self) -> List[str]:
        """Get list of common trading pairs with verified contracts"""
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
            self.verified_networks = {}  # Store verified networks for each symbol
            
            for symbol in common_symbols:
                try:
                    # First verify token contracts
                    is_verified, networks = self.verify_token_contracts(symbol)
                    if not is_verified:
                        continue
                        
                    # Then check trading volume
                    ticker1 = self.exchange1.fetch_ticker(symbol)
                    ticker2 = self.exchange2.fetch_ticker(symbol)
                    
                    if (ticker1.get('quoteVolume', 0) >= self.volume_threshold and 
                        ticker2.get('quoteVolume', 0) >= self.volume_threshold):
                        verified_symbols.append(symbol)
                        self.verified_networks[symbol] = networks
                        self.logger.info(
                            f"Verified {symbol} with volume requirements "
                            f"(Networks: {', '.join(networks)})"
                        )
                    else:
                        self.logger.debug(f"Insufficient volume for {symbol}")
                    
                    time.sleep(self.exchange1.rateLimit / 1000)
                    
                except Exception as e:
                    self.logger.warning(f"Error verifying symbol {symbol}: {str(e)}")
                    continue
            
            self.logger.info(f"Found {len(verified_symbols)} fully verified symbols")
            return verified_symbols
            
        except Exception as e:
            self.logger.error(f"Error getting common symbols: {str(e)}")
            return []

    def get_market_data(self, exchange: ccxt.Exchange, symbol: str) -> Tuple[Dict, Dict, float]:
        """Get market data including orderbook and ticker"""
        try:
            orderbook = exchange.fetch_order_book(symbol, 20)  # Get top 20 orders
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
            
            # Get verified networks for this symbol
            supported_networks = self.verified_networks.get(symbol, [])
            
            return {
                'symbol': symbol,
                'bitget_bid': round(bid1, 8),
                'bitget_ask': round(ask1, 8),
                'mexc_bid': round(bid2, 8),
                'mexc_ask': round(ask2, 8),
                'spread1': round(spread1, 4),
                'spread2': round(spread2, 4),
                'best_spread': round(max(spread1, spread2), 4),
                'direction': 'Bitget→MEXC' if spread1 > spread2 else 'MEXC→Bitget',
                'supported_networks': supported_networks,
                'bitget_depth': round(volume1, 2),
                'mexc_depth': round(volume2, 2),
                'bitget_volume_24h': round(ticker1.get('quoteVolume', 0), 2),
                'mexc_volume_24h': round(ticker2.get('quoteVolume', 0), 2),
                'bitget_liquidity_score': round(liquidity1, 2),
                'mexc_liquidity_score': round(liquidity2, 2),
                'min_liquidity_score': round(min(liquidity1, liquidity2), 2),
                'executable_volume': round(executable_volume, 2)
            }
        except Exception as e:
            self.logger.error(f"Error calculating arbitrage for {symbol}: {str(e)}")
            return None

    async def notify_opportunities(self, opportunities: List[Dict]):
        """Send notifications for arbitrage opportunities"""
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
        """Find and display best arbitrage opportunities"""
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
            
            # Sort by combined factors
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
    """Main execution function"""
    try:
        trader = EnhancedTrading()
        trader.find_arbitrage_opportunities()
    except Exception as e:
        print(f"Program execution failed: {str(e)}")

if __name__ == "__main__":
    main()
