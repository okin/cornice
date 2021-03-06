# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
import warnings

import json
import simplejson

from pyramid import httpexceptions as exc
from pyramid.compat import string_types
from pyramid.renderers import IRendererFactory
from pyramid.response import Response


__all__ = ['json_renderer', 'to_list', 'json_error', 'match_accept_header']


def is_string(s):
    return isinstance(s, string_types)


def json_renderer(helper):
    return _JsonRenderer()


class _JsonRenderer(object):
    """We implement JSON serialization using a combination of our own custom
      Content-Type logic `[1]`_ and Pyramid's default JSON rendering machinery.

      This allows developers to config the JSON renderer using Pyramid's
      configuration machinery `[2]`_.

      .. _`[1]`: https://github.com/mozilla-services/cornice/pull/116 \
                 #issuecomment-14355865
      .. _`[2]`: http://pyramid.readthedocs.io/en/latest/narr/renderers.html \
                 #serializing-custom-objects
    """
    acceptable = ('application/json', 'text/plain')

    def __call__(self, data, context):
        """Serialise the ``data`` with the Pyramid renderer."""
        # Unpack the context.
        request = context['request']
        response = request.response
        registry = request.registry

        # Serialise the ``data`` object to a JSON string using the
        # JSON renderer registered with Pyramid.
        renderer_factory = registry.queryUtility(IRendererFactory, name='json')

        # XXX Patched with ``simplejson.dumps(..., use-decimal=True)``
        # if the renderer has been configured to serialise using just
        # ``json.dumps(...)``.  This maintains backwards compatibility
        # with the Cornice renderer, whilst allowing Pyramid renderer
        # configuration via ``add_adapter`` calls, at the price of
        # rather fragile patching of instance properties.
        if renderer_factory.serializer == json.dumps:
            renderer_factory.serializer = simplejson.dumps
        if 'use_decimal' not in renderer_factory.kw:
            renderer_factory.kw['use_decimal'] = True
        renderer = renderer_factory(None)

        # XXX This call has the side effect of potentially setting the
        # ``response.content_type``.
        json_str = renderer(data, context)

        # XXX So we (re)set it ourselves here, i.e.: *after* the previous call.
        content_type = (request.accept.best_match(self.acceptable) or
                        self.acceptable[0])
        response.content_type = content_type
        return json_str


def to_list(obj):
    """Convert an object to a list if it is not already one"""
    if not isinstance(obj, (list, tuple)):
        obj = [obj, ]
    return obj


class _JSONError(exc.HTTPError):
    def __init__(self, errors, status=400):
        body = {'status': 'error', 'errors': errors}
        Response.__init__(self, simplejson.dumps(body, use_decimal=True))
        self.status = status
        self.content_type = 'application/json'


def json_error(request):
    """Returns an HTTPError with the given status and message.

    The HTTP error content type is "application/json"
    """
    return _JSONError(request.errors, request.errors.status)


def match_accept_header(func, context, request):
    """
    Return True if the request ``Accept`` header match
    the list returned by the callable specified in :param:func.

    Also attach the total list of possible accepted
    egress media types to the request.

    Utility function for performing content negotiation.

    :param func:
        The callable returning the list of acceptable
        internet media types for content negotiation.
        It obtains the request object as single argument.
    """
    acceptable = to_list(func(request))
    request.info['acceptable'] = acceptable
    return request.accept.best_match(acceptable) is not None


def match_content_type_header(func, context, request):
    """
    Return True if the request ``Content-Type`` header match
    the list returned by the callable specified in :param:func.

    Also attach the total list of possible accepted
    ingress media types to the request.

    Utility function for performing request body
    media type checks.

    :param func:
        The callable returning the list of acceptable
        internet media types for request body
        media type checks.
        It obtains the request object as single argument.
    """
    supported_contenttypes = to_list(func(request))
    request.info['supported_contenttypes'] = supported_contenttypes
    return content_type_matches(request, supported_contenttypes)


def extract_json_data(request):
    warnings.warn("Use ``cornice.validators.extract_cstruct()`` instead",
                  DeprecationWarning)
    from cornice.validators import extract_cstruct
    return extract_cstruct(request)['body']


def extract_form_urlencoded_data(request):
    warnings.warn("Use ``cornice.validators.extract_cstruct()`` instead",
                  DeprecationWarning)
    return request.POST


def content_type_matches(request, content_types):
    """
    Check whether ``request.content_type``
    matches given list of content types.
    """
    return request.content_type in content_types


class ContentTypePredicate(object):
    """
    Pyramid predicate for matching against ``Content-Type`` request header.
    Should live in ``pyramid.config.predicates``.

    .. seealso::
      http://docs.pylonsproject.org/projects/pyramid/en/latest/narr/hooks.html
      #view-and-route-predicates
    """
    def __init__(self, val, config):
        self.val = val

    def text(self):
        return 'content_type = %s' % (self.val,)

    phash = text

    def __call__(self, context, request):
        return request.content_type == self.val


def func_name(f):
    """Return the name of a function or class method."""
    if isinstance(f, string_types):
        return f
    elif hasattr(f, '__qualname__'):  # pragma: no cover
        return f.__qualname__  # Python 3
    elif hasattr(f, 'im_class'):  # pragma: no cover
        return '{0}.{1}'.format(f.im_class.__name__, f.__name__)  # Python 2
    else:  # pragma: no cover
        return f.__name__  # Python 2


def current_service(request):
    """Return the Cornice service matching the specified request.

    :returns: the service or None if unmatched.
    :rtype: cornice.Service
    """
    if request.matched_route:
        services = request.registry.cornice_services
        pattern = request.matched_route.pattern
        name = request.matched_route.name
        # try pattern first, then route name else return None
        service = services.get(pattern, services.get('__cornice' + name))
        return service
