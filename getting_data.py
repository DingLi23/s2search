import json, os
import numpy as np, yaml
import pandas as pd
from ranker_helper import get_scores

feature_key_list = ['title', 'abstract', 'venue', 'authors', 'year', 'n_citations']
categorical_feature_key_list = ['title', 'abstract', 'venue', 'authors']

def get(exp_name, sample_name):
    exp_dir = '.'
    conf_path = os.path.join(exp_dir, 'conf.yml')
    with open(conf_path, 'r') as f:
        conf = yaml.safe_load(f)
        samples_config = conf.get('samples')

    # sample_file_list = samples_config.keys()
    print(f'Got sample data: {sample_name}')

    # preparing data
    score_dir = os.path.join(exp_dir, 'scores')

    sample_data_and_config = []
    sample_task_list = samples_config[sample_name]

    t_count = 0
    for task in sample_task_list:
        t_count += 1
        sample_query = task['query']
        sample_masking_option_keys = task['masking_option_keys']

        sample_origin_npy = np.load(os.path.join(score_dir, f'{exp_name}_{sample_name}_t{t_count}_origin.npz'))['arr_0']

        sample_feature_masking_npy = []
        for key in sample_masking_option_keys:
            sample_feature_masking_npy.append(np.load(os.path.join(score_dir, f'{exp_name}_{sample_name}_t{t_count}_{key}.npz'))['arr_0'])
        if len(sample_feature_masking_npy) > 0:
            feature_stack = np.stack((sample_feature_masking_npy))
        else:
            feature_stack = np.stack(([sample_origin_npy]))
            sample_masking_option_keys.append('_origin')

        sample_data_and_config.append({
            'sample_and_task_name': f'{sample_name}',
            'task_number': t_count,
            'query': sample_query,
            'origin': sample_origin_npy,
            'feature_stack': feature_stack,
            'masking_option_keys': sample_masking_option_keys
        })

    return sample_data_and_config

def load_sample_data(exp_name, sample_name, sort=None):
    data = []
    if os.getcwd().endswith('/s2search'):
        os.chdir(os.path.join(os.getcwd(), 'pipelining'))
    else:
        while not os.getcwd().endswith('/pipelining'):
            path_parent = os.path.dirname(os.getcwd())
            os.chdir(path_parent)

    with open(os.path.join(os.getcwd(), exp_name, f'{sample_name}.data')) as f:
        lines = f.readlines()
        for line in lines:
            data.append(json.loads(line.strip()))
            
    if sort != None:
        if sort == 'year':
            data.sort(key = lambda x: x['year'])
    return data

def load_sample(exp_name, sample_name, sort = None, del_f = ['id', 's2_id'], rank_f=None, query=None, author_as_str=False, task_name = None):
    data = []
    original_dir = os.getcwd()
    if os.getcwd().endswith('/s2search'):
        os.chdir(os.path.join(os.getcwd(), 'pipelining'))
    else:
        while not os.getcwd().endswith('/pipelining'):
            path_parent = os.path.dirname(os.getcwd())
            os.chdir(path_parent)

    with open(os.path.join(os.getcwd(), exp_name, f'{sample_name}.data')) as f:
        lines = f.readlines()
        for line in lines:
            jso = json.loads(line.strip())
            if del_f != None:
                for k in del_f:
                    if jso.get(k) != None:
                        del jso[k]
            if author_as_str:
                jso['authors'] = json.dumps(jso['authors'])
            data.append(jso)
            
    os.chdir(original_dir)
            
    if sort != None:
        if sort == 'year' or sort == 'n_citations':
            data.sort(key = lambda x: x[sort])
        else:
            # masking
            df = pd.read_json(f"[{','.join(list(map(lambda x: json.dumps(x), data)))}]")
            dfd = df.drop([x for x in feature_key_list if x != sort], axis=1)
            masked_paper = json.loads(dfd.to_json(orient='records'))
            # ranking
            masked_scores = rank_f(query, masked_paper, task_name=task_name)
            scores_df = pd.DataFrame(data={'score': masked_scores})
            return pd.concat([df, scores_df], axis=1).sort_values(by=['score'])           
            
    return pd.read_json(f"[{','.join(list(map(lambda x: json.dumps(x), data)))}]")

def read_conf(exp_dir_path):
    conf_path = os.path.join(exp_dir_path, 'conf.yml')
    with open(str(conf_path), 'r') as f:
        conf = yaml.safe_load(f)
        return conf.get('description'), conf.get('samples'), conf.get('sample_from_other_exp'),

def remove_duplicate(seq):
    seen = set()
    seen_add = seen.add
    return [x for x in seq if not (x in seen or seen_add(x))]

def get_categorical_encoded_data(data_exp_name, data_sample_name, query, paper_data=None):
    if paper_data == None:
        dff = load_sample(data_exp_name, data_sample_name)
        paper_data = json.loads(dff.to_json(orient='records'))
        
    categorical_name = {}
    
    for i in range(len(feature_key_list)):
        feature_name = feature_key_list[i]
        if feature_name in categorical_feature_key_list:
            df = load_sample(data_exp_name, data_sample_name, query=query, sort=feature_name, rank_f=get_scores)
            if feature_name == 'authors':
                l = [json.dumps(x) for x in df[feature_name]]
            else:
                l = list(df[feature_name])
            categorical_name[i] = remove_duplicate(l)
            
    categorical_name_map = {}
    for i in range(len(feature_key_list)):
        feature_name = feature_key_list[i]
        if feature_name in categorical_feature_key_list:
            categorical_name_map[i] = {}
            values = categorical_name[i]
            for j in range(len(values)):
                value = values[j]
                categorical_name_map[i][value] = j

    # encoding data
    for i in range(len(paper_data)):
        paper_data[i] = [
            categorical_name_map[0][paper_data[i]['title']], categorical_name_map[1][paper_data[i]['abstract']],
            categorical_name_map[2][paper_data[i]['venue']], categorical_name_map[3][json.dumps(paper_data[i]['authors'])],
            paper_data[i]['year'],
            paper_data[i]['n_citations']
        ]
        
    paper_data = np.array(paper_data)
    
    return (categorical_name, paper_data)

def decode_paper(categorical_name, encoded_p):
    return dict(
        title=categorical_name[0][int(encoded_p[0])],
        abstract=categorical_name[1][int(encoded_p[1])],
        venue=categorical_name[2][int(encoded_p[2])],
        authors=json.loads(categorical_name[3][int(encoded_p[3])]),
        year=encoded_p[4],
        n_citations=encoded_p[5],
    )