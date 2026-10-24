// Loaded automatically by react-scripts' Jest config before every test file.
import { TextDecoder, TextEncoder } from 'util';

// React 19: tell React this environment drives updates through act().
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// jsdom 16 (Jest 27) lacks these; react-router v7 needs them at import time.
if (typeof globalThis.TextEncoder === 'undefined') globalThis.TextEncoder = TextEncoder;
if (typeof globalThis.TextDecoder === 'undefined') globalThis.TextDecoder = TextDecoder;
