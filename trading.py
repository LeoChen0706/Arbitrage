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
        """Get token information with proper contract address parsing"""
        try:
            cache_key = f"{exchange.id}_{symbol}"
            if cache_key in self.token_info_cache:
                return self.token_info_cache[cache_key]
            
            market = exchange.markets.get(symbol)
            if not market:
                return None
                
            base = market['base']
            currencies = exchange.fetch_currencies()
            if base not in currencies:
                return None
                
            currency_info = currencies[base]
            
            # Better logging of raw info
            self.logger.info(f"\n{exchange.id} raw info for {symbol}:")
            if 'info' in currency_info:
                # Log each network separately for clarity
                if isinstance(currency_info['info'], dict):
                    for key, value in currency_info['info'].items():
                        self.logger.info(f"{key}: {value}")
            
            networks = {}
            contract_addresses = {}
            
            # Handle MEXC specific structure
            if exchange.id == 'mexc':
                if 'info' in currency_info:
                    chains_info = currency_info['info']
                    network_list = chains_info.get('networkList', [])
                    
                    # Try both networkList and direct chain info
                    if not network_list and 'network' in chains_info:
                        network_list = [chains_info]
                    
                    # Log each network being processed
                    for chain in network_list:
                        self.logger.info(f"Processing MEXC network: {chain}")
                        network = chain.get('network', '').upper()
                        if not network:
                            continue
                            
                        contract = chain.get('contract') or chain.get('sameAddress')
                        if contract:
                            networks[network] = {
                                'network': network,
                                'contract': contract.lower(),
                                'withdrawEnabled': chain.get('withdrawEnable', True),
                                'depositEnabled': chain.get('depositEnable', True)
                            }
                            contract_addresses[network] = contract.lower()
                            self.logger.info(f"Found MEXC contract for {symbol} on {network}: {contract}")
            
            # Handle Bitget specific structure
            elif exchange.id == 'bitget':
                if 'info' in currency_info and isinstance(currency_info['info'], dict):
                    chains = currency_info['info'].get('chains', [])
                    if isinstance(chains, list):
                        # Log each chain being processed
                        for chain in chains:
                            self.logger.info(f"Processing Bitget chain: {chain}")
                            network = chain.get('chain', '').upper()
                            if not network:
                                continue
                                
                            contract = chain.get('contract') or chain.get('contractAddress')
                            if contract:
                                networks[network] = {
                                    'network': network,
                                    'contract': contract.lower(),
                                    'withdrawEnabled': chain.get('withdrawEnable', True),
                                    'depositEnabled': chain.get('depositEnable', True)
                                }
                                contract_addresses[network] = contract.lower()
                                self.logger.info(f"Found Bitget contract for {symbol} on {network}: {contract}")
            
            # Log final results
            self.logger.info(f"Final networks found for {symbol}:")
            for network, info in networks.items():
                self.logger.info(f"Network: {network}, Contract: {info['contract']}")
            
            token_info = {
                'symbol': base,
                'networks': networks,
                'contract_addresses': contract_addresses,
            }
            
            self.token_info_cache[cache_key] = token_info
            return token_info
            
        except Exception as e:
            self.logger.error(f"Error getting token info for {symbol} on {exchange.id}: {str(e)}")
            self.logger.exception(e)  # This will print the full stack trace
            return None
    
    # Option 1: Rename the function to match what's being called
    def verify_token_contracts(self, symbol: str) -> bool:  # Changed from verify_token_compatibility
        """Verify tokens match exactly by checking contract addresses"""
        try:
            token1 = self.get_token_info(self.exchange1, symbol)
            token2 = self.get_token_info(self.exchange2, symbol)
            
            if not token1 or not token2:
                return False
                
            # Find matching networks with contract addresses
            networks1 = set(token1['contract_addresses'].keys())
            networks2 = set(token2['contract_addresses'].keys())
            
            common_networks = networks1.intersection(networks2)
            if not common_networks:
                self.logger.debug(f"{symbol}: No common networks with contracts")
                return False
                
            # Verify contract addresses match exactly
            for network in common_networks:
                addr1 = token1['contract_addresses'][network]
                addr2 = token2['contract_addresses'][network]
                
                if addr1.lower() != addr2.lower():
                    self.logger.warning(f"{symbol} contract mismatch on {network}:")
                    self.logger.warning(f"Bitget: {addr1}")
                    self.logger.warning(f"MEXC: {addr2}")
                    return False
                else:
                    self.logger.info(f"Verified {symbol} contract on {network}: {addr1}")
            
            return True
    
        except Exception as e:
            self.logger.error(f"Error verifying {symbol}: {str(e)}")
            return False
    
    # And update get_common_symbols to use the correct function name
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
            for symbol in common_symbols:
                try:
                    if self.verify_token_contracts(symbol):  # Using the correct function name
                        # Check trading volume
                        ticker1 = self.exchange1.fetch_ticker(symbol)
                        ticker2 = self.exchange2.fetch_ticker(symbol)
                        
                        if (ticker1.get('quoteVolume', 0) >= self.volume_threshold and 
                            ticker2.get('quoteVolume', 0) >= self.volume_threshold):
                            verified_symbols.append(symbol)
                            self.logger.info(f"Verified {symbol}")
                        else:
                            self.logger.debug(f"{symbol}: Insufficient volume")
                    
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
        """Calculate arbitrage opportunities focusing on price differences"""
        try:
            # Get basic market data
            orderbook1 = self.exchange1.fetch_order_book(symbol)
            orderbook2 = self.exchange2.fetch_order_book(symbol)
            
            if not orderbook1 or not orderbook2:
                return None
                
            # Get best bid/ask prices and volumes
            bid1, bid_vol1 = orderbook1['bids'][0] if orderbook1['bids'] else (0, 0)
            ask1, ask_vol1 = orderbook1['asks'][0] if orderbook1['asks'] else (0, 0)
            bid2, bid_vol2 = orderbook2['bids'][0] if orderbook2['bids'] else (0, 0)
            ask2, ask_vol2 = orderbook2['asks'][0] if orderbook2['asks'] else (0, 0)
            
            # Skip if any price is 0
            if not all([bid1, ask1, bid2, ask2]):
                return None
                
            # Calculate spreads
            spread1 = ((bid2 - ask1) / ask1) * 100  # Bitget→MEXC
            spread2 = ((bid1 - ask2) / ask2) * 100  # MEXC→Bitget
            
            # Calculate executable volume based on direction
            if spread1 > spread2:
                # Bitget→MEXC: Buy on Bitget (ask_vol1) and sell on MEXC (bid_vol2)
                executable_volume = min(ask_vol1, bid_vol2)
            else:
                # MEXC→Bitget: Buy on MEXC (ask_vol2) and sell on Bitget (bid_vol1)
                executable_volume = min(ask_vol2, bid_vol1)
            
            # Get verified networks
            token1 = self.get_token_info(self.exchange1, symbol)
            token2 = self.get_token_info(self.exchange2, symbol)
            
            supported_networks = []
            if token1 and token2:
                networks1 = set(token1['contract_addresses'].keys())
                networks2 = set(token2['contract_addresses'].keys())
                for network in networks1.intersection(networks2):
                    if token1['contract_addresses'][network].lower() == token2['contract_addresses'][network].lower():
                        supported_networks.append(network)
            
            best_spread = max(spread1, spread2)
            if best_spread <= 0:
                return None
                
            return {
                'symbol': symbol,
                'bitget_bid': round(bid1, 8),
                'bitget_ask': round(ask1, 8),
                'mexc_bid': round(bid2, 8),
                'mexc_ask': round(ask2, 8),
                'spread1': round(spread1, 4),
                'spread2': round(spread2, 4),
                'best_spread': round(best_spread, 4),
                'direction': 'Bitget→MEXC' if spread1 > spread2 else 'MEXC→Bitget',
                'executable_volume': round(executable_volume, 2),
                'supported_networks': supported_networks
            }
            
        except Exception as e:
            self.logger.error(f"Error calculating arbitrage for {symbol}: {str(e)}")
            return None

    def find_arbitrage_opportunities(self) -> None:
        """Find top 5 arbitrage opportunities sorted by spread"""
        try:
            self.logger.info("Starting arbitrage scan...")
            
            common_symbols = self.get_common_symbols()
            self.logger.info(f"Found {len(common_symbols)} verified common symbols")
            
            opportunities = []
            for symbol in common_symbols:
                result = self.calculate_arbitrage(symbol)
                if result and result['best_spread'] > 0:  # Only check if spread is positive
                    opportunities.append(result)
                time.sleep(self.exchange1.rateLimit / 1000)
            
            # Sort by spread and get top 5
            opportunities.sort(key=lambda x: x['best_spread'], reverse=True)
            top_opportunities = opportunities[:5]
            
            # Display results
            self.logger.info("\nBest arbitrage opportunities:")
            for opp in top_opportunities:
                self.logger.info(
                    f"\nPair: {opp['symbol']}"
                    f"\nDirection: {opp['direction']}"
                    f"\nSpread: {opp['best_spread']}%"
                    f"\nBitget: {opp['bitget_ask']}/{opp['bitget_bid']}"
                    f"\nMEXC: {opp['mexc_ask']}/{opp['mexc_bid']}"
                    f"\nExecutable Volume: {opp['executable_volume']} USDT"
                    f"\nSupported Networks: {', '.join(opp['supported_networks'])}"
                )
            
            # Save to CSV
            if top_opportunities:
                df = pd.DataFrame(top_opportunities)
                filename = f"arbitrage_opportunities_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                df.to_csv(filename, index=False)
                self.logger.info(f"\nOpportunities saved to {filename}")
                
            # Send notifications if enabled
            if self.notifier:
                asyncio.run(self.notify_opportunities(top_opportunities))
                
        except Exception as e:
            self.logger.error(f"Error finding arbitrage opportunities: {str(e)}")
            self.logger.exception(e)

def main():
    """Main execution function"""
    try:
        trader = EnhancedTrading()
        trader.find_arbitrage_opportunities()
    except Exception as e:
        print(f"Program execution failed: {str(e)}")

if __name__ == "__main__":
    main()
