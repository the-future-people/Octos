"""
Directions to a branch, for the Print Octos app.

GET route/?from=LAT,LNG&to=LAT,LNG&mode=driving|walking

The app asks here; this asks OpenRouteService with the key held in
Railway's settings (ORS_API_KEY), so the key never ships inside the app
where anyone could take it out. The answer is trimmed to what the screen
draws: the line of the route, its distance and time, and the turns.

A route between two points barely changes in ten minutes, so it is kept
that long: a customer opening the map twice costs one request, and the
free allowance (about 2,000 a day) goes a long way.
"""

import logging
import os

import requests
from django.core.cache import cache
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

logger = logging.getLogger(__name__)

PROFILES = {'driving': 'driving-car', 'walking': 'foot-walking'}
ORS = 'https://api.openrouteservice.org/v2/directions/{profile}/geojson'


def _point(raw):
    try:
        lat, lng = (float(x) for x in str(raw).split(','))
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return lat, lng


class RouteView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'storefront'

    def get(self, request):
        start = _point(request.query_params.get('from'))
        end = _point(request.query_params.get('to'))
        mode = request.query_params.get('mode', 'driving')
        if not start or not end or mode not in PROFILES:
            return Response({'detail': 'from, to and mode are needed.'}, status=status.HTTP_400_BAD_REQUEST)

        key = os.environ.get('ORS_API_KEY')
        if not key:
            return Response({'detail': 'Directions are not set up yet.'},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

        # About 11 metres either way is the same route.
        cache_key = 'route:%s:%.4f,%.4f:%.4f,%.4f' % (mode, *start, *end)
        found = cache.get(cache_key)
        if found:
            return Response(found)

        try:
            reply = requests.post(
                ORS.format(profile=PROFILES[mode]),
                json={
                    'coordinates': [[start[1], start[0]], [end[1], end[0]]],
                    'instructions': True,
                    'language': 'en',
                    'units': 'm',
                },
                headers={'Authorization': key},
                timeout=12,
            )
        except requests.RequestException:
            logger.exception('Route request failed')
            return Response({'detail': 'We couldn’t get directions just now.'},
                            status=status.HTTP_502_BAD_GATEWAY)

        if reply.status_code != 200:
            logger.warning('Route refused (%s): %s', reply.status_code, reply.text[:300])
            return Response({'detail': 'We couldn’t find a route from here.'},
                            status=status.HTTP_502_BAD_GATEWAY)

        try:
            feature = reply.json()['features'][0]
            line = feature['geometry']['coordinates']
            summary = feature['properties'].get('summary', {})
            steps = []
            for segment in feature['properties'].get('segments', []):
                for step in segment.get('steps', []):
                    at = line[step['way_points'][0]]
                    steps.append({
                        'instruction': step.get('instruction', ''),
                        'name': step.get('name', '') if step.get('name') not in ('-', None) else '',
                        'type': step.get('type'),
                        'distance_m': round(step.get('distance', 0)),
                        'at': [at[1], at[0]],
                    })
        except (KeyError, IndexError, ValueError, TypeError):
            logger.exception('Route answer not understood')
            return Response({'detail': 'We couldn’t read the route.'}, status=status.HTTP_502_BAD_GATEWAY)

        result = {
            'mode': mode,
            'distance_m': round(summary.get('distance', 0)),
            'duration_s': round(summary.get('duration', 0)),
            'path': [[p[1], p[0]] for p in line],
            'steps': steps,
        }
        cache.set(cache_key, result, 600)
        return Response(result)