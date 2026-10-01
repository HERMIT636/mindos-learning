"""Transparent quality signals; unavailable evidence is never turned into a score."""
from urllib.parse import urlsplit


def evaluate_quality(source: dict, blocks: list[dict], references: list[dict], issues: list[str]) -> dict:
    metadata=source['metadata']
    host=urlsplit(metadata.get('url','')).hostname or ''
    if source['origin']=='user_upload':
        authority='用户上传资料，作者与权威性未核验'
    elif host.endswith('.wikipedia.org') or host=='wikipedia.org':
        authority='Wikipedia 公开协作内容，需核对条目与原始文献'
    elif host in ('github.com','raw.githubusercontent.com'):
        authority='GitHub 公开项目内容，项目身份与正确性需另行核对'
    elif host:
        authority=f'公开网页 {host}，权威性未核验'
    else:
        authority='用户提供文字，原始出处与权威性未核验'
    selected=sum(len(b['text']) for b in blocks)
    total=sum(len(b['text']) for b in metadata['blocks'])
    completeness=f'选定 {len(blocks)} 个完整结构块、{selected}/{total} 字；'
    completeness+='存在解析警告，请核对原文件或网页' if metadata.get('warnings') else '文字已保留，语义完整性仍需审查'
    return {'source_authority':authority,'content_completeness':completeness,
            'freshness':metadata.get('published_time') or '发布时间未知（获取时间不等于发布时间）',
            'multi_source_consistency':'单一文档，尚未交叉核验','user_feedback':'未审查',
            'grounded':bool(references) and not issues,'issues':list(issues)}
