"""Shared, bounded selection of actual course material for all teaching entry points."""
from .discovery import teaching_blocks


def course_materials(store, session, course, section_title=''):
    summaries=store.sources(session,course['id'])
    documents=[store.source(session,course['id'],s['id']) for s in summaries]
    def rank(document):
        matched=any(section_title and section_title in b.get('section_path',[]) for b in document['metadata']['blocks'])
        return (document['origin']!='user_upload',not matched)
    documents.sort(key=rank)
    return [{'id':d['id'],'title':d['title'],'origin':d['origin'],
             'blocks':teaching_blocks(d,section_title,4000),
             'total_blocks':len(d['metadata']['blocks'])} for d in documents[:4]]
