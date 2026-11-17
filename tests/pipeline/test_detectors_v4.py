from types import SimpleNamespace
import yaml
from pathlib import Path
from app.pipeline.detector_config import load_file
from app.pipeline.detectors.logic_other import o4
from app.pipeline import prompts

def test_v4_does_not_change_v3():
    cfg, _ = load_file()
    assert cfg.version == 'detectors-v4'
    assert set(cfg.human_review.confirm) == {'S1','S2','L1'}
    old=yaml.safe_load(Path('config/detectors/detectors-v3.yaml').read_text())
    assert set(old['human_review']['confirm']) == {'P5','P6','P7','S1','S2','L1','O4'}
    assert prompts.prompt_set_hash().startswith('prompts-v6:')

def test_o4_without_questions_is_not_zero_unanswered():
    class Context:
        objections=[]
        acoustic={'main':{'silences_ms':[[0,6000]],'loudness_range_db':3,'pitch_range_st':2}}
        cfg=SimpleNamespace(o4=SimpleNamespace(dead_air_ms=5000))
        def seg(self,_):return {'start_ms':0,'end_ms':60000}
        def ask(self,task,payload):
            assert task=='o4_control'
            assert payload['objections_source']=='none'
            assert payload['measured']['unanswered_objections'] is None
            assert payload['measured']['max_response_latency_s'] is None
            return {'level':12,'reason':'声学参考','confidence':.8}
        def ev(self,*a,**kw):return kw
    result=o4(Context())
    assert result[0]['judgment']==12 and '无观众提问' in result[0]['reason']
