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
        """Verify if tokens are the same by checking contract addresses"""
        try:
            # Get currency info from both exchanges
            base = symbol.split('/')[0]  # Get base currency (e.g., 'BTC' from 'BTC/USDT')
            
            bitget_currencies = self.bitget.fetch_currencies()
            mexc_currencies = self.mexc.fetch_currencies()
            
            if base not in bitget_currencies or base not in mexc_currencies:
                return False
            
            bitget_info = bitget_currencies[base]
            mexc_info = mexc_currencies[base]
            
            # Debug log
            self.logger.info(f"\nVerifying {symbol}")
            self.logger.info(f"Bitget info: {bitget_info.get('info', {})}")
            self.logger.info(f"MEXC info: {mexc_info.get('info', {})}")
            
            # Get contract addresses from Bitget
            bitget_contracts = {}
            if 'info' in bitget_info and isinstance(bitget_info['info'], dict):
                chains = bitget_info['info'].get('chains', [])
                for chain in chains:
                    if isinstance(chain, dict):
                        network = chain.get('chainName', '').upper()
                        contract = chain.get('contractAddress')
                        if network and contract:
                            bitget_contracts[network] = contract.lower()
                            self.logger.info(f"Found Bitget contract on {network}: {contract}")
            
            # Get contract addresses from MEXC
            mexc_contracts = {}
            if 'info' in mexc_info:
                chains_info = mexc_info['info']
                network_list = chains_info.get('networkList', [])
                if not network_list and isinstance(chains_info, dict):
                    network_list = [chains_info]
                
                for chain in network_list:
                    if isinstance(chain, dict):
                        network = chain.get('network', '').upper()
                        contract = chain.get('contract') or chain.get('contractAddress')
                        if network and contract:
                            mexc_contracts[network] = contract.lower()
                            self.logger.info(f"Found MEXC contract on {network}: {contract}")
            
            # Check if we have any matching contracts
            for network in set(bitget_contracts.keys()) & set(mexc_contracts.keys()):
                if bitget_contracts[network] == mexc_contracts[network]:
                    self.logger.info(f"Verified {symbol} on {network} with contract {bitget_contracts[network]}")
                    return True
                else:
                    self.logger.info(f"Contract mismatch for {symbol} on {network}:")
                    self.logger.info(f"Bitget: {bitget_contracts[network]}")
                    self.logger.info(f"MEXC: {mexc_contracts[network]}")
            
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

    def calculate_arbitrage(self, symbol):
        try:
            # Get orderbooks
            book1 = self.bitget.fetch_order_book(symbol)
            book2 = self.mexc.fetch_order_book(symbol)
            
            # Get best prices
            bitget_bid = book1['bids'][0][0] if book1['bids'] else 0
            bitget_ask = book1['asks'][0][0] if book1['asks'] else 0
            mexc_bid = book2['bids'][0][0] if book2['bids'] else 0
            mexc_ask = book2['asks'][0][0] if book2['asks'] else 0
            
            if not all([bitget_bid, bitget_ask, mexc_bid, mexc_ask]):
                return None
                
            # Calculate spreads
            spread1 = ((mexc_bid - bitget_ask) / bitget_ask) * 100  # Buy on Bitget, Sell on MEXC
            spread2 = ((bitget_bid - mexc_ask) / mexc_ask) * 100  # Buy on MEXC, Sell on Bitget
            
            # Get executable volume
            volume = min(book1['bids'][0][1], book2['asks'][0][1])
            
            return {
                'symbol': symbol,
                'spread': max(spread1, spread2),
                'direction': 'Bitget→MEXC' if spread1 > spread2 else 'MEXC→Bitget',
                'bitget_bid': bitget_bid,
                'bitget_ask': bitget_ask,
                'mexc_bid': mexc_bid,
                'mexc_ask': mexc_ask,
                'volume': volume
            }
        except Exception as e:
            self.logger.error(f"Error calculating arbitrage for {symbol}: {e}")
            return None

    async def send_telegram_alert(self, opp):
        if not self.bot:
            return
            
        message = (
            f"💰 Arbitrage Opportunity\n\n"
            f"Pair: {opp['symbol']}\n"
            f"Direction: {opp['direction']}\n"
            f"Spread: {opp['spread']:.2f}%\n"
            f"Volume: {opp['volume']:.2f} USDT\n\n"
            f"Bitget: {opp['bitget_ask']}/{opp['bitget_bid']}\n"
            f"MEXC: {opp['mexc_ask']}/{opp['mexc_bid']}"
        )
        
        try:
            await self.bot.send_message(chat_id=self.chat_id, text=message)
        except Exception as e:
            self.logger.error(f"Telegram error: {e}")

    async def scan_opportunities(self):
        self.logger.info("Starting arbitrage scan...")
        
        # Get common pairs
        pairs = self.get_common_pairs()
        self.logger.info(f"Found {len(pairs)} common pairs")
        
        # Calculate arbitrage for each pair
        opportunities = []
        for pair in pairs:
            result = self.calculate_arbitrage(pair)
            if result and result['spread'] > 0:
                opportunities.append(result)
            time.sleep(0.1)  # Rate limiting
        
        # Sort by spread and get top 5
        opportunities.sort(key=lambda x: x['spread'], reverse=True)
        top_5 = opportunities[:5]
        
        # Log results
        self.logger.info("\nTop 5 Arbitrage Opportunities:")
        for opp in top_5:
            self.logger.info(
                f"\nPair: {opp['symbol']}"
                f"\nDirection: {opp['direction']}"
                f"\nSpread: {opp['spread']:.2f}%"
                f"\nVolume: {opp['volume']:.2f} USDT"
                f"\nBitget: {opp['bitget_ask']}/{opp['bitget_bid']}"
                f"\nMEXC: {opp['mexc_ask']}/{opp['mexc_bid']}"
            )
            
            # Send Telegram alert
            await self.send_telegram_alert(opp)
        
        # Save to CSV
        if top_5:
            df = pd.DataFrame(top_5)
            df.to_csv(f"opportunities_{datetime.now().strftime('%Y%m%d_%H%M')}.csv", index=False)

async def main():
    scanner = ArbitrageScanner()
    await scanner.scan_opportunities()

if __name__ == "__main__":
    asyncio.run(main())
