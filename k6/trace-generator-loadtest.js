import { check, sleep } from 'k6';
import http from 'k6/http';

const BASE_URL = __ENV.K6_TRACE_GENERATOR_URL || 'http://trace-generator:8000';

const PROMPTS = [
    'Analyze the quarterly revenue report for EMEA region.',
    'Summarize the customer feedback from last month.',
    'Extract key insights from the product usage data.',
    'Generate a risk assessment report for the Q4 roadmap.',
    'Review and respond to the partnership proposal.',
    'Identify trends in the sales data from the past year.',
    'Draft a technical summary of the system architecture changes.',
    'Evaluate the performance metrics for the ML pipeline.',
    'Compare pricing strategies across the top 5 competitors.',
    'Classify support tickets by urgency and category.',
];

const TENANTS = ['acme-corp', 'globex', 'initech', 'umbrella', 'hooli'];
const AGENTS  = ['document-analyzer', 'email-responder', 'data-extractor', 'report-generator'];
const MODELS  = ['gpt-4o', 'gpt-4o-mini', 'claude-sonnet-4-6', 'claude-haiku-4-5'];

function pick(arr) {
    return arr[Math.floor(Math.random() * arr.length)];
}

export default function () {
    const rand = Math.random();

    if (rand < 0.05) {
        // ~5% probe-error calls — exercises the 500 monitoring path
        const res = http.get(`${BASE_URL}/probe/error`);
        check(res, { 'probe/error returns 500': (r) => r.status === 500 });
        sleep(1);
        return;
    }

    if (rand < 0.10) {
        // ~5% log-generation calls — exercises the log pipeline
        const payload = JSON.stringify({
            count: Math.floor(Math.random() * 5) + 1,
            level: pick(['info', 'warning', 'error']),
        });
        const res = http.post(`${BASE_URL}/logs`, payload, {
            headers: { 'Content-Type': 'application/json' },
        });
        check(res, { 'logs status 200': (r) => r.status === 200 });
        sleep(1);
        return;
    }

    // ~90% normal trace generation
    const payload = JSON.stringify({
        prompt:  pick(PROMPTS),
        tenant:  pick(TENANTS),
        agent:   pick(AGENTS),
        model:   pick(MODELS),
    });

    const res = http.post(`${BASE_URL}/generate`, payload, {
        headers:  { 'Content-Type': 'application/json' },
        timeout:  '10s',
    });

    check(res, {
        'generate status 200': (r) => r.status === 200,
        'generate has trace_id': (r) => {
            try { return JSON.parse(r.body).trace_id !== undefined; } catch { return false; }
        },
        'generate time < 5s': (r) => r.timings.duration < 5000,
    });

    // /generate already takes 0.6–4 s; a short extra sleep keeps VU load gentle
    sleep(0.5);
}
