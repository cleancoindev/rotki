#!/usr/bin/env python
#
# Good kraken and python resource:
# https://github.com/zertrin/clikraken/tree/master/clikraken

import urllib
import urllib2
import hmac
import hashlib
import base64
import time

from utils import query_fiat_pair, retry_calls, rlk_jsonloads, convert_to_int
from order_formatting import AssetMovement
from exchange import Exchange
from errors import KrakenAPIRateLimitExceeded
from fval import FVal


# TODO: Figure out why registering the exception class here
# does not seem to work.
# Problem is that `cls.__custom_class_to_dict_registry[clazz] = converter`
# returns nothing so the converter lookup fails.
#
# Examples are here: https://github.com/irmen/Pyro4/tree/master/examples/ser_custom
# Until then using normal exceptions.
class KrakenError(Exception):
    def __init__(self, err):
        self.err = "Kraken Error: {}".format(err)

    def __str__(self):
        return self.err


def to_dict_converter(obj):
    print("GOT IN TO_DICT")
    return {
        '__class__': 'KrakenError',
        'error': obj.err
    }


def from_dict_converter(class_name, dictionary):
    print("GOT IN FROM_DICT")
    if class_name == 'KrakenError':
        return KrakenError(dictionary['error'])
    else:
        raise ValueError('Unrecognized class')


KRAKEN_TO_WORLD = {
    'XDAO': 'DAO',
    'XETC': 'ETC',
    'XETH': 'ETH',
    'XLTC': 'LTC',
    'XREP': 'REP',
    'XXBT': 'BTC',
    'XXMR': 'XMR',
    'ZEUR': 'EUR',
    'XMLN': 'MLN',
    'XICN': 'ICN',
}

WORLD_TO_KRAKEN = {
    'ETC': 'XETC',
    'ETH': 'XETH',
    'LTC': 'XLTC',
    'REP': 'XREP',
    'BTC': 'XXBT',
    'XMR': 'XXMR',
    'EUR': 'ZEUR',
    'DAO': 'XDAO',
    'MLN': 'XMLN',
    'ICN': 'XICN',
}


def kraken_to_world_pair(pair):
    p1 = pair[:4]
    p2 = pair[4:]
    world_p1 = KRAKEN_TO_WORLD[p1]
    world_p2 = KRAKEN_TO_WORLD[p2]
    return world_p1 + '_' + world_p2


class Kraken(Exchange):
    def __init__(self, api_key, secret, args, logger, data_dir):
        super(Kraken, self).__init__('kraken', api_key, secret)
        self.uri = 'https://api.kraken.com'
        self.apiversion = '0'
        self.log = logger
        self.data_dir = data_dir
        self.usdprice = {}
        self.eurprice = {}

    def first_connection(self):
        if self.first_connection_made:
            return

        resp = self.query_private(
            'TradeVolume',
            req={'pair': 'XETHXXBT', 'fee-info': True}
        )
        # Assuming all fees are the same for all pairs that we trade here,
        # as long as they are normal orders on normal pairs.
        self.taker_fee = FVal(resp['fees']['XETHXXBT']['fee'])
        self.maker_fee = FVal(resp['fees_maker']['XETHXXBT']['fee'])
        self.tradeable_pairs = self.query_public('AssetPairs')
        self.first_connection_made = True
        # Also need to do at least a single pass of the main logic for the ticker
        self.main_logic()

    def _query_public(self, method, req={}):
        """API queries that do not require a valid key/secret pair.

        Arguments:
        method -- API method name (string, no default)
        req    -- additional API request parameters (default: {})
        """
        urlpath = '/' + self.apiversion + '/public/' + method
        post_data = urllib.urlencode(req)
        ret = urllib2.urlopen(
            urllib2.Request(
                'https://api.kraken.com' + urlpath,
                post_data
            )
        )
        json_ret = rlk_jsonloads(ret.read())
        if json_ret['error']:
            if isinstance(json_ret['error'], list):
                error = json_ret['error'][0]
            else:
                error = json_ret['error']
            if 'Rate limit exceeded' in error:
                raise KrakenAPIRateLimitExceeded(method)
            else:
                raise ValueError(error)

        return json_ret['result']

    def query_public(self, method, req={}):
        return retry_calls(5, 'kraken', method, self._query_public, method, req)

    def query_private(self, method, req={}):
        return retry_calls(5, 'kraken', method, self._query_private, method, req)

    def _query_private(self, method, req={}):
        """API queries that require a valid key/secret pair.

        Arguments:
        method -- API method name (string, no default)
        req    -- additional API request parameters (default: {})

        """
        urlpath = '/' + self.apiversion + '/private/' + method

        req['nonce'] = int(1000 * time.time())
        post_data = urllib.urlencode(req)
        message = urlpath + hashlib.sha256(
            str(req['nonce']) + post_data).digest()
        signature = hmac.new(
            base64.b64decode(self.secret),
            message,
            hashlib.sha512
        )
        headers = {
            'API-Key': self.api_key,
            'API-Sign': base64.b64encode(signature.digest())
        }
        ret = urllib2.urlopen(
            urllib2.Request(
                'https://api.kraken.com' + urlpath,
                post_data,
                headers)
        )
        json_ret = rlk_jsonloads(ret.read())
        if json_ret['error']:
            if isinstance(json_ret['error'], list):
                error = json_ret['error'][0]
            else:
                error = json_ret['error']
            if 'Rate limit exceeded' in error:
                raise KrakenAPIRateLimitExceeded(method)
            else:
                raise ValueError(error)

        return json_ret['result']

    def world_to_kraken_pair(self, pair):
        p1, p2 = pair.split('_')
        kraken_p1 = WORLD_TO_KRAKEN[p1]
        kraken_p2 = WORLD_TO_KRAKEN[p2]
        if kraken_p1 + kraken_p2 in self.tradeable_pairs:
            pair = kraken_p1 + kraken_p2
        elif kraken_p2 + kraken_p1 in self.tradeable_pairs:
            pair = kraken_p2 + kraken_p1
        else:
            raise ValueError('Unknown pair "{}" provided'.format(pair))
        return pair

    # ---- General exchanges interface ----
    def order_book(self, currencyPair):
        resp = self.query_public('Depth', req={'pair': currencyPair})
        return resp[currencyPair]

    def main_logic(self):
        if not self.first_connection_made:
            return

        self.ticker = self.query_public(
            'Ticker',
            req={'pair': ','.join(self.tradeable_pairs.keys())}
        )
        self.eurprice['BTC'] = FVal(self.ticker['XXBTZEUR']['c'][0])
        self.usdprice['BTC'] = FVal(self.ticker['XXBTZUSD']['c'][0])
        self.eurprice['ETH'] = FVal(self.ticker['XETHZEUR']['c'][0])
        self.usdprice['ETH'] = FVal(self.ticker['XETHZUSD']['c'][0])
        self.eurprice['REP'] = FVal(self.ticker['XREPZEUR']['c'][0])
        self.usdprice['REP'] = FVal(self.ticker['XREPZUSD']['c'][0])
        self.eurprice['XMR'] = FVal(self.ticker['XXMRZEUR']['c'][0])
        self.usdprice['XMR'] = FVal(self.ticker['XXMRZUSD']['c'][0])
        self.eurprice['ETC'] = FVal(self.ticker['XETCZEUR']['c'][0])
        self.usdprice['ETC'] = FVal(self.ticker['XETCZUSD']['c'][0])

    def find_fiat_price(self, asset):
        """Find USD/EUR price of asset. The asset should be in the kraken style.
        e.g.: XICN. Save both prices in the kraken object and then return the
        USD price.
        """
        pair = asset + 'XXBT'
        if pair not in self.tradeable_pairs:
            raise ValueError(
                'Could not find a BTC tradeable pair in kraken for "{}"'.format(asset)
            )
        btc_price = FVal(self.ticker[pair]['c'][0])
        common_name = KRAKEN_TO_WORLD[asset]
        self.usdprice[common_name] = btc_price * self.usdprice['BTC']
        self.eurprice[common_name] = btc_price * self.eurprice['BTC']
        return self.usdprice[common_name]

    def query_balances(self, ignore_cache=False):
        self.first_connection()

        old_balances = self.query_private('Balance', req={})

        # find USD price of EUR
        self.usdprice['EUR'] = query_fiat_pair('EUR', 'USD')

        balances = dict()
        for k, v in old_balances.iteritems():
            v = FVal(v)
            if v == FVal(0):
                continue

            common_name = KRAKEN_TO_WORLD[k]
            entry = {}
            entry['amount'] = v
            if common_name in self.usdprice:
                entry['usd_value'] = v * self.usdprice[common_name]
            else:
                entry['usd_value'] = v * self.find_fiat_price(k)

            balances[common_name] = entry

        return balances

    def query_until_finished(self, endpoint, keyname, start_ts, end_ts, extra_dict=None):
        """ Abstracting away the functionality of querying a kraken endpoint where
        you neen to check the 'count' of the returned results and provide sufficient
        calls with enough offset to gather all the data of your query.
        """
        result = list()

        response = self._query_endpoint_for_period(
            endpoint=endpoint,
            start_ts=start_ts,
            end_ts=end_ts,
            extra_dict=extra_dict
        )
        count = response['count']
        offset = len(response[keyname])
        result.extend(response[keyname].values())

        while offset < count:
            response = self._query_endpoint_for_period(
                endpoint=endpoint,
                start_ts=start_ts,
                end_ts=end_ts,
                offset=offset,
                extra_dict=extra_dict
            )
            assert count == response['count']
            offset += len(response[keyname])
            result.extend(response[keyname].values())

        return result

    def query_trade_history(self, start_ts=None, end_ts=None, end_at_least_ts=None):
        cache = self.check_trades_cache(start_ts, end_at_least_ts)
        if cache is not None:
            return cache
        result = self.query_until_finished('TradesHistory', 'trades', start_ts, end_ts)
        # before returning save it in the disk for future reference
        self.update_trades_cache(result, start_ts, end_ts)
        return result

    def _query_endpoint_for_period(self, endpoint, start_ts, end_ts, offset=None, extra_dict=None):
        request = dict()
        request['start'] = start_ts
        request['end'] = end_ts
        if offset is not None:
            request['ofs'] = offset
        if extra_dict is not None:
            request.update(extra_dict)
        result = self.query_private(endpoint, request)
        return result

    def query_deposits_withdrawals(self, start_ts, end_ts, end_at_least_ts):
        cache = self.check_trades_cache(
            start_ts,
            end_at_least_ts,
            special_name='deposits_withdrawals'
        )
        if cache is not None:
            result = cache
        else:
            result = self.query_until_finished(
                endpoint='Ledgers',
                keyname='ledger',
                start_ts=start_ts,
                end_ts=end_ts,
                extra_dict=dict(type='deposit')
            )
            result.extend(self.query_until_finished(
                endpoint='Ledgers',
                keyname='ledger',
                start_ts=start_ts,
                end_ts=end_ts,
                extra_dict=dict(type='withdrawal')
            ))
            self.update_trades_cache(
                result,
                start_ts,
                end_ts,
                special_name='deposits_withdrawals'
            )

        movements = list()
        for movement in result:
            movements.append(AssetMovement(
                exchange='kraken',
                category=movement['type'],
                # Kraken timestamps have floating point
                timestamp=convert_to_int(movement['time'], accept_only_exact=False),
                asset=KRAKEN_TO_WORLD[movement['asset']],
                amount=FVal(movement['amount']),
                fee=FVal(movement['fee'])
            ))
        return movements

    def set_buy(self, pair, amount, price):
        pair = WORLD_TO_KRAKEN(pair)
        req = {
            'pair': pair,
            'type': 'buy',
            'ordertype': 'limit',
            'price': price,
            'volume': amount,
            'oflags': 'post',
            'trading_agreement': 'agree'
        }
        resp = self.query_private('AddOrder', req=req)
        self.log.lognotify("Buy Set", "{}".format(resp))
