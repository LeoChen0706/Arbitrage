def get_token_info(self, exchange: ccxt.Exchange, symbol: str) -> Optional[Dict]:
        """Get detailed token information including contract addresses"""
        try:
            cache_key = f"{exchange.id}_{symbol}"
            if cache_key in self.token_info_cache:
                return self.token_info_cache[cache_key]

            # Get currency information
            currencies = exchange.fetch_currencies()
            base = symbol.split('/')[0]
            
            if base not in currencies:
                self.logger.warning(f"Currency {base} not found in {exchange.id}")
                return None

            currency_info = currencies[base]
            networks = {}
            contract_addresses = {}

            # Handle different exchange API structures
            if 'networks' in currency_info:
                for network, info in currency_info['networks'].items():
                    contract = info.get('contract')
                    if contract:
                        networks[network.upper()] = {
                            'contract': contract.lower(),
                            'withdrawEnabled': info.get('withdraw', True),
                            'depositEnabled': info.get('deposit', True)
                        }
                        contract_addresses[network.upper()] = contract.lower()
            
            # Handle MEXC's specific structure
            elif exchange.id == 'mexc' and 'info' in currency_info:
                if isinstance(currency_info['info'], dict) and 'chains' in currency_info['info']:
                    for chain in currency_info['info']['chains']:
                        if isinstance(chain, dict):
                            network = chain.get('chain', '').upper()
                            contract = chain.get('contract_address')
                            if network and contract:
                                networks[network] = {
                                    'contract': contract.lower(),
                                    'withdrawEnabled': True,
                                    'depositEnabled': True
                                }
                                contract_addresses[network] = contract.lower()

            # Handle Bitget's structure
            elif exchange.id == 'bitget' and 'info' in currency_info:
                if isinstance(currency_info['info'], dict):
                    chains = currency_info['info'].get('chains', [])
                    if isinstance(chains, list):
                        for chain in chains:
                            if isinstance(chain, dict):
                                network = chain.get('chainName', '').upper()
                                contract = chain.get('contractAddress')
                                if network and contract:
                                    networks[network] = {
                                        'contract': contract.lower(),
                                        'withdrawEnabled': chain.get('withdrawEnable', True),
                                        'depositEnabled': chain.get('depositEnable', True)
                                    }
                                    contract_addresses[network] = contract.lower()

            token_info = {
                'symbol': base,
                'networks': networks,
                'contract_addresses': contract_addresses
            }
            
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
                self.logger.warning(f"Could not get token info for {symbol}")
                return False, []

            # Find common networks
            common_networks = set(token1['networks'].keys()) & set(token2['networks'].keys())
            if not common_networks:
                self.logger.warning(f"{symbol} has no common networks between exchanges")
                return False, []

            # Verify contracts match for each common network
            verified_networks = []
            for network in common_networks:
                contract1 = token1['networks'][network]['contract']
                contract2 = token2['networks'][network]['contract']
                
                if contract1 and contract2:
                    if contract1.lower() == contract2.lower():
                        # Verify deposit/withdraw status
                        if (token1['networks'][network]['withdrawEnabled'] and 
                            token1['networks'][network]['depositEnabled'] and
                            token2['networks'][network]['withdrawEnabled'] and
                            token2['networks'][network]['depositEnabled']):
                            verified_networks.append(network)
                        else:
                            self.logger.warning(f"{symbol} on {network} has disabled deposit/withdraw")
                    else:
                        self.logger.warning(
                            f"Contract mismatch for {symbol} on {network}:\n"
                            f"Bitget: {contract1}\n"
                            f"MEXC: {contract2}"
                        )

            if verified_networks:
                self.logger.info(f"{symbol} verified on networks: {', '.join(verified_networks)}")
                return True, verified_networks
            else:
                self.logger.warning(f"No verified networks found for {symbol}")
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
            verified_networks = {}  # Store verified networks for each symbol
            
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
                        verified_networks[symbol] = networks
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
            
            # Store verified networks for use in calculate_arbitrage
            self.verified_networks = verified_networks
            return verified_symbols
            
        except Exception as e:
            self.logger.error(f"Error getting common symbols: {str(e)}")
            return []

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
                'bitget_bid': bid1,
                'bitget_ask': ask1,
                'mexc_bid': bid2,
                'mexc_ask': ask2,
                'spread1': spread1,
                'spread2': spread2,
                'best_spread': max(spread1, spread2),
                'direction': 'Bitget→MEXC' if spread1 > spread2 else 'MEXC→Bitget',
                'supported_networks': supported_networks,
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
