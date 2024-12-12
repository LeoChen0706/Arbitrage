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
            
            # Handle MEXC's structure
            elif exchange.id == 'mexc':
                if 'info' in currency_info and isinstance(currency_info['info'], dict):
                    chains = currency_info['info'].get('chains', [])
                    if isinstance(chains, list):
                        for chain in chains:
                            if isinstance(chain, dict):
                                network = chain.get('chain', '').upper()
                                contract = chain.get('contract_address')
                                if network and contract:
                                    network = self.normalize_network_name(network)
                                    token_info['contracts'][network] = contract.lower()
                                    token_info['networks'].add(network)
            
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
