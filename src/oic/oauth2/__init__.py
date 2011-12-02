#!/usr/bin/env python
#
__author__ = 'rohe0002'

import httplib2
import time
import base64
import inspect

from oic.utils import time_util
from oic.oauth2.message import *

Version = "2.0"

HTTP_ARGS = ["headers", "redirections", "connection_type"]

DEFAULT_POST_CONTENT_TYPE = 'application/x-www-form-urlencoded'

REQUEST2ENDPOINT = {
    AuthorizationRequest: "authorization_endpoint",
    AccessTokenRequest: "token_endpoint",
#    ROPCAccessTokenRequest: "authorization_endpoint",
#    CCAccessTokenRequest: "authorization_endpoint",
    RefreshAccessTokenRequest: "token_endpoint",
    TokenRevocationRequest: "token_endpoint",
}

RESPONSE2ERROR = {
    AuthorizationResponse: [AuthorizationErrorResponse, TokenErrorResponse],
    AccessTokenResponse: [TokenErrorResponse]
}

class Token(object):
    def __init__(self, resp=None):
        for prop in AccessTokenResponse.c_attributes.keys():
            _val = getattr(resp, prop)
            if _val:
                setattr(self, prop, _val)

        for key, val in resp.c_extension.items():
            setattr(self, key, val)

        if resp.expires_in:
            _tet = time_util.time_sans_frac() + int(resp.expires_in)
        else:
            _tet = 0
        self.token_expiration_time = int(_tet)


    def is_valid(self):
        if self.token_expiration_time:
            if time.time() > self.token_expiration_time:
                return False

        return True

    def __str__(self):
        return "%s" % self.__dict__

    def keys(self):
        return self.__dict__.keys()

class Grant(object):
    def __init__(self, exp_in=600, resp=None):
        self.grant_expiration_time = 0
        self.exp_in = exp_in
        self.tokens = []
        if resp:
            if isinstance(resp, AuthorizationResponse):
                self.add_code(resp)
            elif isinstance(resp, AccessTokenResponse):
                self.add_token(resp)

    @classmethod
    def from_code(cls, resp):
        instance = cls()
        instance.add_code(resp)
        return instance

    def add_code(self, resp):
        self.code = resp.code
        self.grant_expiration_time = time_util.time_sans_frac() + self.exp_in

    def add_token(self, resp):
        self.tokens.append(Token(resp))
        
    def is_valid(self):
        if time.time() > self.grant_expiration_time:
            return False
        else:
            return True

    def __str__(self):
        return "%s" % self.__dict__

    def keys(self):
        return self.__dict__.keys()

    def update(self, resp):
        if isinstance(resp, AccessTokenResponse):
            self.tokens.append(Token(resp))
        elif isinstance(resp, AuthorizationResponse):
            self.add_code(resp)

    def get_token(self, scope=""):
        token = None
        if scope:
            for token in self.tokens:
                if scope in token.scope:
                    return token
        else:
            for token in self.tokens:
                if token.is_valid():
                    return token

        return token

class Client(object):
    def __init__(self, client_id=None, cache=None, http_timeout=None,
                 proxy_info=None, follow_redirects=True,
                 disable_ssl_certificate_validation=False,
                 ca_certs="", key=None,
                 algorithm="HS256", grant_expire_in=600, client_secret="",
                 client_timeout=0):

        self.http = httplib2.Http(cache, http_timeout, proxy_info, ca_certs,
            disable_ssl_certificate_validation=disable_ssl_certificate_validation)
        self.http.follow_redirects = follow_redirects

        self.client_id = client_id
        self.client_secret = client_secret
        self.client_timeout = client_timeout

        self.state = None
        self.nonce = None

        self.grant_expire_in = grant_expire_in
        self.grant = {}

        # own endpoint
        self.redirect_uri = None

        # service endpoints
        self.authorization_endpoint=None
        self.token_endpoint=None
        self.token_revocation_endpoint=None

        self.key = key
        self.algorithm = algorithm
        self.request2endpoint = REQUEST2ENDPOINT
        self.response2error = RESPONSE2ERROR

    def reset(self):
        self.state = None
        self.nonce = None

        self.grant = {}

        self.authorization_endpoint=None
        self.token_endpoint=None
        self.redirect_uri = None

    def grant_from_state(self, state):
        for key, grant in self.grant.items():
            if key == state:
                return grant

        return None

#    def scope_from_state(self, state):
#
#    def grant_from_state_or_scope(self, state, scope):

    def _parse_args(self, klass, **kwargs):
        ar_args = {}
        for prop, val in kwargs.items():
            if prop in klass.c_attributes:
                ar_args[prop] = val
            elif prop.startswith("extra_"):
                if prop[6:] not in klass.c_attributes:
                    ar_args[prop[6:]] = val

        # Used to not overwrite defaults
        argspec = inspect.getargspec(klass.__init__)
        for prop in klass.c_attributes.keys():
            if prop not in ar_args:
                index = argspec[0].index(prop) -1 # skip self
                if not argspec[3][index]:
                    ar_args[prop] = getattr(self, prop, None)

        return ar_args

    def _endpoint(self, endpoint, **kwargs):
        try:
            uri = kwargs[endpoint]
            if uri:
                del kwargs[endpoint]
        except KeyError:
            uri = ""

        if not uri:
            try:
                uri = getattr(self, endpoint)
            except Exception:
                raise Exception("No '%s' specified" % endpoint)

        if not uri:
            raise Exception("No '%s' specified" % endpoint)

        return uri

    def _get_token(self, **kwargs):
        token = None
        try:
            token = kwargs["token"]
        except KeyError:
            if "state" and "scope" in kwargs:
                token = self.grant[kwargs["state"]].get_token(kwargs["scope"])
            else:
                try:
                    token = self.grant[kwargs["state"]].get_token("")
                except KeyError:
                    pass

        if token and token.is_valid():
            return token
        else:
            return None

    def construct_request(self, reqclass, request_args=None, extra_args=None):
        if request_args is None:
            request_args = {}
            
        args = self._parse_args(reqclass, **request_args)
        if extra_args:
            args.update(extra_args)
        return reqclass(**args)

    #noinspection PyUnusedLocal
    def construct_AuthorizationRequest(self, reqclass=AuthorizationRequest,
                                       request_args=None, extra_args=None,
                                       **kwargs):

        if request_args is not None:
            try: # change default
                self.redirect_uri = request_args["redirect_uri"]
            except KeyError:
                pass

        return self.construct_request(reqclass, request_args, extra_args)

    #noinspection PyUnusedLocal
    def construct_AccessTokenRequest(self, cls=AccessTokenRequest,
                                     request_args=None, extra_args=None,
                                     **kwargs):

        try:
            grant = self.grant[kwargs["state"]]
        except KeyError:
            raise Exception("Missing grant")

        if not grant.is_valid():
            raise GrantExpired("Authorization Code to old %s > %s" % (time.time(),
                                                grant.grant_expiration_time))

        if request_args is None:
            request_args = {}

        request_args["code"] = grant.code

        if "grant_type" not in request_args:
            request_args["grant_type"] = "authorization_code"

        return self.construct_request(cls, request_args, extra_args)

    def construct_RefreshAccessTokenRequest(self,
                                            cls=RefreshAccessTokenRequest,
                                            request_args=None, extra_args=None,
                                            **kwargs):

        if request_args is None:
            request_args = {}

        token = self._get_token(**kwargs)
        if token is None:
            raise Exception("No valid token available")
        
        request_args["refresh_token"] = token.refresh_token

        try:
            request_args["scope"] = token.scope
        except AttributeError:
            pass
        
        return self.construct_request(cls, request_args, extra_args)

    def construct_TokenRevocationRequest(self, cls=TokenRevocationRequest,
                                         request_args=None, extra_args=None,
                                         **kwargs):

        if request_args is None:
            request_args = {}

        token = self._get_token(**kwargs)

        request_args["token"] = token.access_token
        return self.construct_request(cls, request_args, extra_args)

    def request_info(self, cls, method="POST", request_args=None,
                     extra_args=None, **kwargs):

        if request_args is None:
            request_args = {}
            
        cis = getattr(self, "construct_%s" % cls.__name__)(cls, request_args,
                                                           extra_args,
                                                           **kwargs)

        uri = self._endpoint(self.request2endpoint[cls], **request_args)

        if extra_args:
            extend = True
        else:
            extend = False

        if method == "POST":
            body = cis.get_urlencoded(extended=extend)
        else: # assume GET
            uri = "%s?%s" % (uri, cis.get_urlencoded(extended=extend))
            body = None

        if method == "POST":
            h_args = {"headers": {"content-type": DEFAULT_POST_CONTENT_TYPE}}
        else:
            h_args = {}

        return uri, body, h_args, cis


    def parse_response(self, cls, info="", format="json", state="",
                       extended=False, response2error=None):
        """
        Parse a response

        :param cls: Which class to use when parsing the response
        :param info: The response, can be either an JSON code or an urlencoded
            form:
        :param format: Which serialization that was used
        :param extended: If non-standard parametrar should be honored
        :return: The parsed and to some extend verified response
        """

        _r2e = self.response2error

        resp = None
        if format == "json":
            try:
                resp = cls.set_json(info, extended)
                assert resp.verify()
            except Exception, err:
                aresp = resp
                serr = ""

                for errcls in _r2e[cls]:
                    try:
                        resp = errcls.set_json(info, extended)
                        resp.verify()
                        break
                    except Exception, serr:
                        resp = None

                if not resp:
                    if aresp and aresp.keys():
                        raise ValueError("Parse error: %s" % err)
                    else:
                        raise ValueError("Parse error: %s" % serr)

        elif format == "urlencoded":
            if '?' in info:
                parts = urlparse.urlparse(info)
                scheme, netloc, path, params, query, fragment = parts[:6]
            else:
                query = info

            try:
                resp = cls.set_urlencoded(query, extended)
                assert resp.verify()
            except Exception, err:
                aresp = resp
                serr = ""

                for errcls in _r2e[cls]:
                    try:
                        resp = errcls.set_urlencoded(query, extended)
                        resp.verify()
                        break
                    except Exception, serr:
                        resp = None

                if not resp:
                    if aresp and aresp.keys():
                        raise ValueError("Parse error: %s" % err)
                    else:
                        raise ValueError("Parse error: %s" % serr)

        else:
            raise Exception("Unknown package format: '%s'" %  format)

        try:
            _state = resp.state
        except (AttributeError, KeyError):
            _state = ""
            
        if not _state:
            _state = state

        try:
            self.grant[_state].update(resp)
        except KeyError:
            self.grant[_state] = Grant(resp=resp)

        return resp

    def request_and_return(self, url, respcls=None, method="GET", body=None,
                        return_format="json", extended=True,
                        state="", http_args=None):
        """
        :param url: The URL to which the request should be sent
        :param respcls: The class the should represent the response
        :param method: Which HTTP method to use
        :param body: A message body if any
        :param return_format: The format of the body of the return message
        :param extended: If non-standard parametrar should be honored
        :param http_args: Arguments for the HTTP client
        :return: A respcls or ErrorResponse instance or True if no response
            body was expected.
        """

        if http_args is None:
            http_args = {}

        if "password" in http_args:
            self.http.add_credentials(self.client_id, http_args["password"])

        try:
            response, content = self.http.request(url, method, body=body,
                                                  **http_args)
        except Exception:
            raise

        if response.status == 200:
            if return_format == "":
                pass
            elif return_format == "json":
                assert "application/json" in response["content-type"]
            elif return_format == "urlencoded":
                assert DEFAULT_POST_CONTENT_TYPE in response["content-type"]
            else:
                raise ValueError("Unknown return format: %s" % return_format)
        elif response.status == 500:
            raise Exception("ERROR: Something went wrong: %s" % content)
        else:
            raise Exception("ERROR: Something went wrong [%s]" % response.status)

        if return_format:
            return self.parse_response(respcls, content, return_format,
                                       state, extended)
        else:
            return True

    def do_authorization_request(self, cls=AuthorizationRequest,
                                 state="", return_format="", method="GET",
                                 request_args=None, extra_args=None,
                                 http_args=None, resp_cls=None):

        url, body, ht_args, csi = self.request_info(cls,
                                                    request_args=request_args,
                                                    extra_args=extra_args)

        if http_args is None:
            http_args = ht_args
        else:
            http_args.update(http_args)

        resp = self.request_and_return(url, resp_cls, method, body,
                                       return_format, extended=False,
                                       state=state, http_args=http_args)

        if isinstance(resp, ErrorResponse):
            resp.state = csi.state

        return resp

    def do_access_token_request(self, cls=AccessTokenRequest, scope="",
                                state="", return_format="json", method="POST",
                                request_args=None, extra_args=None,
                                http_args=None, resp_cls=AccessTokenResponse):

        # method is default POST
        url, body, ht_args, csi = self.request_info(cls, method=method,
                                                    request_args=request_args,
                                                    extra_args=extra_args,
                                                    scope=scope, state=state)

        if http_args is None:
            http_args = ht_args
        else:
            http_args.update(http_args)

        return self.request_and_return(url, resp_cls, method, body,
                                       return_format, extended=False,
                                       state=state, http_args=http_args)

    def do_access_token_refresh(self, cls=RefreshAccessTokenRequest,
                                state="", return_format="json", method="POST",
                                request_args=None, extra_args=None,
                                http_args=None, resp_cls=AccessTokenResponse,
                                **kwargs):

        token = self._get_token(state=state, **kwargs)
        url, body, ht_args, csi = self.request_info(cls, method=method,
                                                    request_args=request_args,
                                                    extra_args=extra_args,
                                                    token=token)

        if http_args is None:
            http_args = ht_args
        else:
            http_args.update(http_args)

        return self.request_and_return(url, resp_cls, method, body,
                                       return_format, extended=False,
                                       state=state, http_args=http_args)

    def do_revocate_token(self, cls=TokenRevocationRequest, scope="", state="",
                          return_format="json", method="POST",
                          request_args=None, extra_args=None, http_args=None,
                          resp_cls=None):

        url, body, ht_args, csi = self.request_info(cls, method=method,
                                                    request_args=request_args,
                                                    extra_args=extra_args,
                                                    scope=scope, state=state)

        if http_args is None:
            http_args = ht_args
        else:
            http_args.update(http_args)

        return self.request_and_return(url, resp_cls, method, body,
                                       return_format, extended=False,
                                       state=state, http_args=http_args)

    def fetch_protected_resource(self, uri, method="GET", headers=None,
                                 state="", scope="", **kwargs):

        token = self.grant[state].get_token(scope)
        if not token:
            raise Exception("No suitable token available")
        
        if not token.is_valid():
            # The token is to old, refresh
            self.do_access_token_refresh()

        if headers is None:
            headers = {}

        try:
            _acc_token = kwargs["access_token"]
            del kwargs["access_token"]
        except KeyError:
            _acc_token= self.grant[scope].access_token

        headers["Authorization"] = "Bearer %s" % base64.encodestring(_acc_token)

        return self.http.request(uri, method, headers=headers, **kwargs)

class Server(object):
    def __init__(self):
        pass

    def parse_url_request(self, cls, url=None, query=None, extended=False):
        if url:
            parts = urlparse.urlparse(url)
            scheme, netloc, path, params, query, fragment = parts[:6]

        req = cls.set_urlencoded(query, extended)
        req.verify()
        return req

    def parse_authorization_request(self, rcls=AuthorizationRequest,
                                    url=None, query=None, extended=False):
        
        return self.parse_url_request(rcls, url, query, extended)

    def parse_jwt_request(self, rcls=AuthorizationRequest, txt="", key="",
                          verify=True, extend=False):
        areq = rcls.set_jwt(txt, key, verify, extend)
        areq.verify()
        return areq

    def parse_body_request(self, cls=AccessTokenRequest, body=None,
                           extend=False):
        req = cls.set_urlencoded(body, extend)
        req.verify()
        return req

    def parse_token_request(self, rcls=AccessTokenRequest, body=None,
                            extend=False):
        return self.parse_body_request(rcls, body, extend)

    def parse_refresh_token_request(self, rcls=RefreshAccessTokenRequest,
                                    body=None, extend=False):
        return self.parse_body_request(rcls, body, extend)

#    def is_authorized(self, path, authorization=None):
#        if not authorization:
#            return False
#
#        if authorization.startswith("Bearer"):
#            parts = authorization.split(" ")
#
#        return True


import hashlib
from Crypto.Cipher import AES

class Crypt():
    def __init__(self, password, mode=AES.MODE_CBC):
        self.password = password or 'kitty'
        self.key = hashlib.sha256(password).digest()
        self.mode = mode

    def encrypt(self, text):
        encryptor = AES.new(self.key, self.mode)

        if len(text) % 16:
            text += ' ' * (16 - len(text) % 16)
            
        return encryptor.encrypt(text)

    def decrypt(self, ciphertext):
        decryptor = AES.new(self.key, self.mode)
        return decryptor.decrypt(ciphertext)
    

if __name__ == "__main__":
    import doctest
    doctest.testmod()