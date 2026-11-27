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

BASELINE_METHOD_DIGESTS = {
    "qbittorrent": QBITTORRENT_METHOD_DIGESTS,
    "transmission": TRANSMISSION_METHOD_DIGESTS,
}

# 3.1.4–3.1.6 的上述方法与原基线一致；3.1.7–3.1.8 为下列实现。
# 仅收录已审查路径调用顺序并通过隔离回归的源码，不按版本号跳过检查。
REVIEWED_RELEASES = {
    "3.1.4": "09f62ff87e196df9e39a6422f23c23860610d96a",
    "3.1.5": "99ee18d0e6a27422a4affd3d4ec7d8d56772e4c3",
    "3.1.6": "dd4d83a00933d21772709212dc24d1b80f0e48ad",
    "3.1.7": "1f7bddc8372d7ff63d10122efb2b0873b2bfd499",
    "3.1.8": "015df3826503329f3b185847bd8a3e0b13c8559f",
    "3.2.2": "c609abc782978eb81efe1da1dcf259bd3ff6e635",
    "3.2.8": "b88c7295d9a4711c87478f9d6307762c8ca73233",
    "3.2.14": "d644a9e904893f243d347fb266054636f68d321d",
}

UPDATED_METHOD_DIGESTS = {
    "qbittorrent": {
        "download": "865fb4ead4d4feade49a164f259167d666b8dd5639a3fb3d8fc852e10e824975",
        "get_default_config_name": "e289088fed58259992f774d25f547a39ccd173265155e3a7e46a8153247f1e5a",
        "init_module": "02ccf08450c45b257dab3b43dbb02e51a61d3c3551c63a1cc85bb5ffae654e71",
        "list_torrents": "2df0d2b6af227e3b2c0d340162678b864106986faea085923f962952be8199e2",
        "normalize_path": "ec784b77439e7f050361aaca474515cb463c7fe482a879a85b8578b4f682dfa4",
        "normalize_return_path": "4e4ec67d4794581afe78baff71da2803ae07bc09daecbc5cd1cab6f73ab3e7dd",
        "update_torrent": "e9449e69e0b0a807c57edc453669e0ead9c6a50ae93219428a260f714a0c79e7",
    },
    "transmission": {
        "download": "0b1af48db01d272bd06d4ac9eb1f2f3fcec9f91c55ce9e304596d8896d716a4d",
        "get_default_config_name": "e289088fed58259992f774d25f547a39ccd173265155e3a7e46a8153247f1e5a",
        "init_module": "b142c18edb276947db009903388d342e61c6afbc16e6b03795e381f347bd042d",
        "list_torrents": "3231400a09d8097054186dd0f08078626c43bf843549e8994970c45df4b47f9d",
        "normalize_path": "ec784b77439e7f050361aaca474515cb463c7fe482a879a85b8578b4f682dfa4",
        "normalize_return_path": "4e4ec67d4794581afe78baff71da2803ae07bc09daecbc5cd1cab6f73ab3e7dd",
        "update_torrent": "1e902ae0744bef1489323c4b205321059db9e170cdce84a863292496f083854b",
    },
}

METHOD_DIGESTS = {
    kind: {name: frozenset((digest, UPDATED_METHOD_DIGESTS[kind][name]))
           for name, digest in methods.items()}
    for kind, methods in BASELINE_METHOD_DIGESTS.items()
}

# 3.2.2 的 download 将“下载任务已存在”字面量提取为同值常量，
# 两种下载器的路径调用顺序及其余受检方法与 3.1.8 一致。
RELEASE_3_2_2_DOWNLOAD_DIGESTS = {
    "qbittorrent": "4a794461d61a932d999ffc0458fd98f7f8367db23932d952ff9d2694bcc9a307",
    "transmission": "37a77b3b39a56a2dca84503acf572e9615becfcd8a9582d85f5cb24a35e9e348",
}
for kind, digest in RELEASE_3_2_2_DOWNLOAD_DIGESTS.items():
    METHOD_DIGESTS[kind]["download"] |= frozenset((digest,))

# 3.2.8 新增 episode_selection，已有任务不再重新选集；Transmission
# 使用 add_torrent_with_status 区分重复任务。路径转换顺序及其余受检方法不变。
RELEASE_3_2_8_DOWNLOAD_DIGESTS = {
    "qbittorrent": "94c80af52726b5a7a1f4ef5ac38beab0ee005aa37d69b0b90e91f9d90e033f9f",
    "transmission": "f8d5824856539b21a58b04d1261759d1ea074d67a445ca4c789f1c203a8a89a5",
}
for kind, digest in RELEASE_3_2_8_DOWNLOAD_DIGESTS.items():
    METHOD_DIGESTS[kind]["download"] |= frozenset((digest,))

# 3.2.14 核验已有任务，整理时按原始路径计算未完成文件的相对路径，
# 并从已启用配置实时选择默认下载器。两个路径转换入口仍沿用原实现。
RELEASE_3_2_14_METHOD_DIGESTS = {
    "qbittorrent": {
        "download": "3c6dd5e3ec2edeb0099000c2e31a72c207db4bab0139e4b9e2dbb484dc67505f",
        "list_torrents": "58b41920d1563b130a045df649ebd9b6c11aa158d51946b01b99ff90ec366877",
        "get_default_config_name": "929a94fdd9d5488d7b921b2e2dccb91f73b12de9379ce44c20772229603d63ac",
    },
    "transmission": {
        "download": "a6925c4893347db47ec4b85c8380ebf71d9125fbc65e581032fb8e6a475b7f60",
        "list_torrents": "4c3caab34af557d242d7c238511e7a6bc13c01625b1dee8616893debad507285",
        "get_default_config_name": "929a94fdd9d5488d7b921b2e2dccb91f73b12de9379ce44c20772229603d63ac",
    },
}
for kind, methods in RELEASE_3_2_14_METHOD_DIGESTS.items():
    for name, digest in methods.items():
        METHOD_DIGESTS[kind][name] |= frozenset((digest,))
