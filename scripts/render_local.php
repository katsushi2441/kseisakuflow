<?php
// ローカル確認用: php render_local.php /giin/flow/ai > out.html （xb4g.com として描画）
$_SERVER['REQUEST_URI'] = $argv[1];
$_SERVER['HTTP_HOST'] = 'xb4g.com';
$_SERVER['HTTPS'] = 'on';
chdir('/home/kojima/work/xb4g/giin');
require '/home/kojima/work/xb4g/giin/index.php';
