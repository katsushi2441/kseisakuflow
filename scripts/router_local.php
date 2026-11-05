<?php
// php -S 用のルーター（ローカル確認のみ）。/giin/ 以下を xb4g/giin/index.php に渡す
$_SERVER['HTTP_HOST'] = 'xb4g.com';
$_SERVER['HTTPS'] = 'on';
chdir('/home/kojima/work/xb4g/giin');
require '/home/kojima/work/xb4g/giin/index.php';
