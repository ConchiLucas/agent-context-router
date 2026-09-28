const {test} = require('node:test');
const assert = require('node:assert/strict');
const {responseBody} = require('./capture-core.js');
test('business JSON, null and empty array remain intact', () => {
  assert.deepEqual(responseBody('{"code":9000}'), {code:9000});
  assert.deepEqual(responseBody('[]'), []);
  assert.equal(responseBody('null'), null);
});
test('base64 JSON is not binary', () => {
  assert.deepEqual(responseBody(btoa('{"data":[]}'), true, 'application/json'), {data:[]});
});
test('binary, NUL and oversized text produce bounded metadata', () => {
  assert.equal(responseBody(btoa('PK\x00abc'), true, 'application/zip')._capture_kind, 'binary');
  assert.equal(responseBody('PK\x00abc')._capture_kind, 'binary');
  assert.equal(responseBody('a'.repeat(300000))._capture_kind, 'truncated');
  assert.equal(responseBody('<html>login</html>', false, 'text/html')._capture_kind, 'text');
});
test('JSON URL string stays a string, secrets in objects are redacted', () => {
  assert.equal(responseBody('"https://example.test/?a=1"'), 'https://example.test/?a=1');
  assert.deepEqual(responseBody('{"token":"secret"}'), {token:'[REDACTED]'});
});
