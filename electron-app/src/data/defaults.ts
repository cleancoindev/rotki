export class Defaults {
  static DEFAULT_DISPLAY_FORMAT = '%d/%m/%Y %H:%M:%S %Z';
  static FLOATING_PRECISION = 2;
  static RPC_ENDPOINT = 'http://localhost:8545';
  static BALANCE_SAVE_FREQUENCY = 24;
  static ANONYMIZED_LOGS = false;
  static HISTORICAL_DATA_START = '01/08/2015';
  static ANONYMOUS_USAGE_ANALYTICS = true;
}

export const exchanges = [
  'kraken',
  'poloniex',
  'bittrex',
  'bitmex',
  'binance',
  'coinbase',
  'coinbasepro'
];
