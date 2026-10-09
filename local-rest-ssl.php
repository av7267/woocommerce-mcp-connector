<?php
// DEV ONLY: lets WooCommerce accept key/secret auth on local plain-HTTP API calls.
if (isset($_SERVER['REQUEST_URI']) && strpos($_SERVER['REQUEST_URI'], '/wp-json/') === 0) {
    $_SERVER['HTTPS'] = 'on';
}
