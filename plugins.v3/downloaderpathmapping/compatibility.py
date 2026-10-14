"""已核对的上游方法 AST 摘要；更新时需重新审查调用顺序。"""

UPSTREAM_COMMIT = "99ef7e508b829e81cedaf55b3aea0387baca2515"
MINIMUM_VERSION = "3.1.4"
QBITTORRENT_METHOD_DIGESTS = {
    'download': '1c93dffefbd7baf3a72a2d811fb21dc9c5877a9c7ae3089b7edd15f0942e4634',
    'get_default_config_name': 'c4d162db3295042ab4e531a858ffd95008991d97459cf541875127f8b6289283',
    'init_module': '41a294f4a2974fe13834016746c722a194935bc3941c4641a1487fa339065f9b',
    'list_torrents': '377d18ca46413ea743ad62b80627d1eb0ef369c24652ad6bdd5b42db2f3835b8',
    'normalize_path': '42fb41cb507066d60b45719538689285698f5d444f552f29cef4f1ae10cf11d2',
    'normalize_return_path': '4e4ec67d4794581afe78baff71da2803ae07bc09daecbc5cd1cab6f73ab3e7dd',
    'update_torrent': '04562f31a78f3f91519bb21d5b1e856cf617bca8c746602987855b78f64c593c',
}

TRANSMISSION_METHOD_DIGESTS = {
    'download': '2ea4c772ca0539be21308c25e916bd28ef166d289d627e4f7ea2ae2a92c4ece0',
    'get_default_config_name': 'c4d162db3295042ab4e531a858ffd95008991d97459cf541875127f8b6289283',
    'init_module': '97e604a52ba30c1c56c7b74ee88d4c47f14227f6ce207e1141368b0bd9908308',
    'list_torrents': '2c82e9e938940008ddb99c5aeaca2e5b5b669c007ba3004b5a686171e9663503',
    'normalize_path': '42fb41cb507066d60b45719538689285698f5d444f552f29cef4f1ae10cf11d2',
    'normalize_return_path': '4e4ec67d4794581afe78baff71da2803ae07bc09daecbc5cd1cab6f73ab3e7dd',
    'update_torrent': 'da320c156298619a752026a17c4c6f3ec92c5a655616486d564b58a9f7af0e6c',
}

METHOD_DIGESTS = {
    "qbittorrent": QBITTORRENT_METHOD_DIGESTS,
    "transmission": TRANSMISSION_METHOD_DIGESTS,
}
