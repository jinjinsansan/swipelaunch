import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'https://d-swipe.com';

const SELLER_ENDPOINTS = [
  '/api/points/balance',
  '/api/public/fx?track_view=false',
  '/api/notes/public/10-24-10r-c1',
  '/api/public/salons/b8c2e037-060e-4632-acae-5b7a7bfbfeca',
  '/api/sales/history',
];

export const options = {
  scenarios: {
    smoke: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: 10 },
        { duration: '1m', target: 30 },
        { duration: '30s', target: 0 },
      ],
      gracefulRampDown: '10s',
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<600', 'max<2000'],
    http_req_failed: ['rate<0.02'],
  },
};

export default function () {
  const responses = SELLER_ENDPOINTS.map((path) => http.get(`${BASE_URL}${path}`));

  responses.forEach((res, index) => {
    check(res, {
      [`${SELLER_ENDPOINTS[index]} response is 2xx`]: (r) => r.status >= 200 && r.status < 300,
      [`${SELLER_ENDPOINTS[index]} duration < 800ms`]: (r) => r.timings.duration < 800,
    });
  });

  sleep(1);
}
