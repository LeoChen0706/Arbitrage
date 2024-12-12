import ccxt
import time
import logging
import configparser
from pathlib import Path
import pandas as pd
from datetime import datetime
import telegram
import asyncio

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
    config.read('config/config.ini')
    return config

class ArbitrageScanner:
    def __init__(self):
        self.logger = setup_logging()
        self.config = load_config()
        self.setup_exchanges()
        self.setup_telegram()
        
    def setup_exchanges(self):
        # Setup Bitget
        bitget_config = {
            'apiKey': self.config['Bitget']['api_key'],
            'secret': self.config['Bitget']['secret_key'],
            'password': self.config['Bitget'].get('passphrase', ''),
            'enableRateLimit': True
        }
        self.bitget = ccxt.bitget(bitget_config)
        
        # Setup MEXC
        mexc_config = {
            'apiKey': self.config['MEXC']['api_key'],
            'secret': self.config['MEXC']['secret_key'],
            'enableRateLimit': True
        }
        self.mexc = ccxt.mexc(mexc_config)
        
        # Load markets
        self.bitget.load_markets()
        self.mexc.load_markets()
        
    def setup_telegram(self):
        try:
            bot_token = self.config['Telegram']['bot_token']
            self.chat_id = self.config['Telegram']['chat_id']
            self.bot = telegram.Bot(token=bot_token)
        except:
            self.bot = None
            self.logger.error("Telegram setup failed")

    def verify_token(self, symbol: str) -> bool:
        """Verify tokens by matching any contract address"""
        try:
            base = symbol.split('/')[0]
            
            # Get currency info
            bitget_currencies = self.bitget.fetch_currencies()
            mexc_currencies = self.mexc.fetch_currencies()
            
            if base not in bitget_currencies or base not in mexc_currencies:
                return False
            
            bitget_info = bitget_currencies[base]
            mexc_info = mexc_currencies[base]
            
            # Get all contract addresses from Bitget
            bitget_contracts = set()
            if 'info' in bitget_info and isinstance(bitget_info['info'], dict):
                chains = bitget_info['info'].get('chains', [])
                if isinstance(chains, list):
                    for chain in chains:
                        if isinstance(chain, dict):
                            contract = chain.get('contractAddress', '').lower()
                            if contract:
                                bitget_contracts.add(contract)
                                self.logger.info(f"Found Bitget contract for {symbol}: {contract}")
            
            # Get all contract addresses from MEXC
            mexc_contracts = set()
            if 'info' in mexc_info:
                chains_info = mexc_info['info']
                network_list = chains_info.get('networkList', [])
                if not network_list and isinstance(chains_info, dict):
                    network_list = [chains_info]
                
                for chain in network_list:
                    if isinstance(chain, dict):
                        contract = (chain.get('contract', '') or 
                                  chain.get('contractAddress', '') or 
                                  chain.get('sameAddress', '')).lower()
                        if contract:
                            mexc_contracts.add(contract)
                            self.logger.info(f"Found MEXC contract for {symbol}: {contract}")
            
            # Check if any contract matches
            matching_contracts = bitget_contracts.intersection(mexc_contracts)
            if matching_contracts:
                self.logger.info(f"✅ Verified {symbol} with matching contract: {next(iter(matching_contracts))}")
                return True
            
            return False
            
        except Exception as e:
            self.logger.error(f"Error verifying {symbol}: {str(e)}")
            return False

    def get_common_pairs(self):
        """Get common pairs with verified contract addresses"""
        # Get USDT pairs from both exchanges
        bitget_pairs = set(s for s in self.bitget.symbols if s.endswith('/USDT'))
        mexc_pairs = set(s for s in self.mexc.symbols if s.endswith('/USDT'))
        common_pairs = list(bitget_pairs.intersection(mexc_pairs))
        
        self.logger.info(f"Found {len(common_pairs)} pairs with same name")
        
        # Verify each pair
        verified_pairs = []
        for pair in common_pairs:
            if self.verify_token(pair):
                verified_pairs.append(pair)
                self.logger.info(f"Verified {pair}")
            time.sleep(0.1)  # Rate limiting
        
        self.logger.info(f"Found {len(verified_pairs)} verified pairs")
        return verified_pairs

    def calculate_arbitrage(self, symbol: str) -> Optional[dict]:
        """Calculate arbitrage opportunity with accurate spreads"""
        try:
            # Get orderbooks
            bitget_book = self.bitget.fetch_order_book(symbol)
            mexc_book = self.mexc.fetch_order_book(symbol)
            
            if not bitget_book['bids'] or not bitget_book['asks'] or not mexc_book['bids'] or not mexc_book['asks']:
                return None
            
            # Get best prices
            bitget_bid = float(bitget_book['bids'][0][0])
            bitget_ask = float(bitget_book['asks'][0][0])
            mexc_bid = float(mexc_book['bids'][0][0])
            mexc_ask = float(mexc_book['asks'][0][0])
            
            # Calculate both spreads
            bitget_to_mexc = ((mexc_bid - bitget_ask) / bitget_ask) * 100
            mexc_to_bitget = ((bitget_bid - mexc_ask) / mexc_ask) * 100
            
            # Get executable volumes
            if bitget_to_mexc > mexc_to_bitget:
                direction = 'Bitget→MEXC'
                spread = bitget_to_mexc
                volume = min(float(bitget_book['asks'][0][1]), float(mexc_book['bids'][0][1]))
            else:
                direction = 'MEXC→Bitget'
                spread = mexc_to_bitget
                volume = min(float(mexc_book['asks'][0][1]), float(bitget_book['bids'][0][1]))
            
            # Skip if no profitable opportunity
            if spread <= 0:
                return None
            
            return {
                'symbol': symbol,
                'direction': direction,
                'spread': round(spread, 4),
                'volume': round(volume, 4),
                'bitget_bid': round(bitget_bid, 8),
                'bitget_ask': round(bitget_ask, 8),
                'mexc_bid': round(mexc_bid, 8),
                'mexc_ask': round(mexc_ask, 8)
            }
        
        except Exception as e:
            self.logger.error(f"Error calculating arbitrage for {symbol}: {str(e)}")
            return None

    async def scan_opportunities(self):
        """Scan for top 5 real arbitrage opportunities"""
        self.logger.info("Starting arbitrage scan...")
        
        # Get verified common pairs
        pairs = self.get_common_pairs()
        self.logger.info(f"Found {len(pairs)} verified pairs")
        
        # Calculate arbitrage for each pair
        opportunities = []
        for pair in pairs:
            result = self.calculate_arbitrage(pair)
            if result:  # Only append if there's a profitable opportunity
                opportunities.append(result)
            time.sleep(0.1)  # Rate limiting
        
        # Sort by spread and get true top 5
        opportunities.sort(key=lambda x: x['spread'], reverse=True)
        top_5 = opportunities[:5]
        
        # Log results
        self.logger.info("\nTop 5 Arbitrage Opportunities:")
        for opp in top_5:
            self.logger.info(
                f"\nPair: {opp['symbol']}"
                f"\nDirection: {opp['direction']}"
                f"\nSpread: {opp['spread']}%"
                f"\nVolume: {opp['volume']} USDT"
                f"\nBitget: {opp['bitget_ask']}/{opp['bitget_bid']}"
                f"\nMEXC: {opp['mexc_ask']}/{opp['mexc_bid']}"
            )
            
            # Send Telegram alert
            if self.bot:
                message = (
                    f"💰 Arbitrage Opportunity\n\n"
                    f"Pair: {opp['symbol']}\n"
                    f"Direction: {opp['direction']}\n"
                    f"Spread: {opp['spread']}%\n"
                    f"Volume: {opp['volume']} USDT\n\n"
                    f"Bitget: {opp['bitget_ask']}/{opp['bitget_bid']}\n"
                    f"MEXC: {opp['mexc_ask']}/{opp['mexc_bid']}"
                )
                await self.bot.send_message(chat_id=self.chat_id, text=message)
        
        # Save to CSV
        if top_5:
            df = pd.DataFrame(top_5)
            df.to_csv(f"opportunities_{datetime.now().strftime('%Y%m%d_%H%M')}.csv", index=False)

async def main():
    scanner = ArbitrageScanner()
    await scanner.scan_opportunities()

if __name__ == "__main__":
    asyncio.run(main())
