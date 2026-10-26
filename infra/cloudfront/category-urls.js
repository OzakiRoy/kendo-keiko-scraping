// CloudFront Functions, cloudfront-js-2.0, viewer-request.
// Query names/values are already URI-encoded in the CloudFront event.
function querySuffix(query) {
    var pairs = [];
    Object.keys(query).forEach(function (name) {
        var field = query[name];
        var values = field.multiValue || [field];
        values.forEach(function (item) { pairs.push(name + '=' + item.value); });
    });
    return pairs.length ? '?' + pairs.join('&') : '';
}

function handler(event) {
    var request = event.request;
    if (request.method !== 'GET' && request.method !== 'HEAD') return request;
    var paths = ['/keiko', '/renseikai', '/area/kanto', '/area/tokyo'];
    if (paths.indexOf(request.uri) !== -1) {
        return {
            statusCode: 301,
            statusDescription: 'Moved Permanently',
            headers: {
                location: {value: request.uri + '/' + querySuffix(request.querystring || {})},
                'cache-control': {value: 'no-store'}
            }
        };
    }
    if (paths.indexOf(request.uri.slice(0, -1)) !== -1 && request.uri.slice(-1) === '/') {
        request.uri += 'index.html';
    }
    return request;
}
