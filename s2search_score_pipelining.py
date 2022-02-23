from s2search.rank import S2Ranker
import time
import os
import os.path as path
import sys
import yaml
import json
import shutil
import zlib
from multiprocessing import Pool
import numpy as np
import feature_masking as fm

model_dir = './s2search_data'
data_dir = str(path.join(os.getcwd(), 'pipelining'))
ranker = None
data_loading_line_limit = 1000


def init_ranker():
    global ranker
    if ranker == None:
        print(f'Loading ranker model...')
        st = time.time()
        ranker = S2Ranker(model_dir)
        et = round(time.time() - st, 2)
        print(f'Load the s2 ranker within {et} sec')

def find_weird_score(scores, paper_list):
    weird_paper_idx = []
    weird_paper = []
    for i in range(len(scores)):
        score = scores[i]
        if score > 100:
            weird_paper_idx.append(i)
            weird_paper.append(paper_list[i])
            
    return weird_paper_idx, weird_paper
    

def get_scores(query, paper, mask_option='origin', data_file_name=''):
    init_ranker()
    scores = []
    paper_list = paper
    if len(paper_list) > 1000:
        curr_idx = 0
        while curr_idx < len(paper_list):
            end_idx = curr_idx + 1000 if curr_idx + 1000 < len(paper_list) else len(paper_list)
            curr_list = paper_list[curr_idx: end_idx]
            scores.extend(ranker.score(query, curr_list))
            curr_idx += 1000
    else:
        scores = ranker.score(query, paper_list)
        
    weird_paper_idx, weird_paper = find_weird_score(scores, paper_list)
            
    if len(weird_paper) > 0:
        fixed_score = [ranker.score(query, [one_paper])[0] for one_paper in weird_paper]
        idx = 0
        for weird_idx in weird_paper_idx:
            scores[weird_idx] = fixed_score[idx]
            idx += 0
    
    weird_paper_idx_again, _ = find_weird_score(scores, paper_list)

    if len(weird_paper_idx_again) > 0:
        print(f'still got weird scores')
        
    return scores
    
    init_ranker()
    st = time.time()
    scores = ranker.score(query, paper)

    et = round(time.time() - st, 6)

    return scores


def read_conf(exp_dir_path_str):
    conf_path = path.join(exp_dir_path_str, 'conf.yml')
    with open(str(conf_path), 'r') as f:
        conf = yaml.safe_load(f)
        return conf.get('description'), conf.get('samples'), conf.get('sample_from_other_exp'),


def get_scores_and_save(arg):
    query = arg[0]
    paper_data = arg[1]
    exp_dir_path_str = arg[2]
    npy_file_name = arg[3]
    mask_option = arg[4]

    original_score_npy_file_name = path.join(
        exp_dir_path_str, 'scores', npy_file_name)
    scores = get_scores(query, paper_data, mask_option, npy_file_name)
    incomplete_file = str(original_score_npy_file_name) + '#incomplete.txt'

    scores = [str(score) for score in scores]
    with open(incomplete_file, "a+") as f:
        f.write('\n'.join(scores) + '\n')


def score_file_is_configured(sample_configs, score_file_name):
    score_file_name = score_file_name.replace('.npz', '')
    score_file_name = score_file_name.replace('#incomplete.txt', '')
    exp_name, sample_data_name, task_name, one_masking_options = score_file_name.split(
        '_')

    sample_tasks = sample_configs.get(sample_data_name)
    if sample_tasks != None:
        task_number = int(task_name[1:])
        if len(sample_tasks) >= task_number:
            task = sample_tasks[task_number - 1]
            masking_option_keys = task['masking_option_keys']
            if one_masking_options == 'origin' or one_masking_options in masking_option_keys:
                return True

    return False


def txt_to_npy(exp_dir, exp_name, sample_name, task_name, masking_option_key, et):
    incomplete_file = path.join(
        exp_dir, 'scores', f'{exp_name}_{sample_name}_{task_name}_{masking_option_key}#incomplete.txt')
    arr = np.loadtxt(incomplete_file)
    complete_file = path.join(
        exp_dir, 'scores', f'{exp_name}_{sample_name}_{task_name}_{masking_option_key}')
    np.savez_compressed(complete_file, arr)
    os.remove(incomplete_file)
    print(
        f'Score computing for {exp_name}_{sample_name}_{task_name}_{masking_option_key} is done within {et} sec.')


if __name__ == '__main__':
    if len(sys.argv) > 1:
        exp_list = sys.argv[1:]
        for exp_name in exp_list:
            exp_dir_path = path.join(data_dir, exp_name)
            exp_dir_path_str = str(exp_dir_path)
            if path.isdir(exp_dir_path):
                description, sample_configs, sample_from_other_exp = read_conf(
                    exp_dir_path_str)
                print(
                    f'\nRunning s2search ranker on {exp_name} experiment data')
                print(f'Description of this experiment: {description}')

                # scores dir
                scores_dir = path.join(exp_dir_path_str, 'scores')
                if not path.exists(str(scores_dir)):
                    os.mkdir(str(scores_dir))
                else:
                    for root, dirs, files in os.walk(scores_dir):
                        for file_name in files:
                            # remove score file if it is not configured
                            if not score_file_is_configured(sample_configs, file_name):
                                os.remove(
                                    path.join(exp_dir_path_str, 'scores', file_name))

                # sample_file_list = [f for f in os.listdir(exp_dir_path_str) if path.isfile(path.join(exp_dir_path_str, f)) and f.endswith('.data')]
                sample_file_list = sample_configs.keys()

                for file_name in sample_file_list:
                    sample_name = file_name.replace('.data', '')
                    sample_task_list = sample_configs[sample_name]

                    t_count = 0
                    for task in sample_task_list:
                        t_count += 1
                        sample_query = task['query']
                        sample_masking_option_keys = task['masking_option_keys']
                        data_file_path = path.join(
                            data_dir, exp_name, f'{file_name}.data')
                        if not path.exists(data_file_path):
                            ole_data_file_path = data_file_path
                            data_file_path = path.join(
                                data_dir, *sample_from_other_exp.get(file_name))
                            print(
                                f'Using {data_file_path} for {exp_name} {file_name}')
                        paper_data = []

                        # computing for original
                        using_origin_from = task.get('using_origin_from')
                        target_origin_exist = path.join(
                            exp_dir_path_str, 'scores', f'{exp_name}_{sample_name}_{using_origin_from}_origin.npz')
                        original_npy_file = path.join(
                            exp_dir_path_str, 'scores', f'{exp_name}_{sample_name}_t{t_count}_origin.npz')
                        if using_origin_from != None and target_origin_exist:
                            print(
                                f'Using origin result of {using_origin_from} for {exp_name}_{sample_name}_t{t_count}_origin.npz')
                            shutil.copyfile(target_origin_exist,
                                            original_npy_file)
                        else:
                            if not os.path.exists(original_npy_file):
                                incomplete_original_npy_file = path.join(
                                    exp_dir_path_str, 'scores', f'{exp_name}_{sample_name}_t{t_count}_origin#incomplete.txt')
                                if path.exists(incomplete_original_npy_file):
                                    with open(incomplete_original_npy_file) as f:
                                        previous_progress = len(f.readlines())
                                    print(
                                        f'continue computing: {original_npy_file}')
                                else:
                                    previous_progress = 0
                                    print(
                                        f'start computing: {original_npy_file}')

                                with open(str(data_file_path)) as f:
                                    line_count = 0
                                    idx = 0
                                    st = time.time()
                                    for line in f:
                                        idx += 1
                                        if (idx <= previous_progress):
                                            continue
                                        paper_data.append(json.loads(
                                            line.strip(), strict=False))
                                        line_count += 1
                                        if (line_count == data_loading_line_limit):
                                            get_scores_and_save([
                                                sample_query, paper_data, exp_dir_path_str,
                                                f'{exp_name}_{sample_name}_t{t_count}_origin',
                                                'origin',
                                            ])
                                            paper_data = []
                                            line_count = 0
                                    if len(paper_data) > 0:
                                        get_scores_and_save([
                                            sample_query, paper_data, exp_dir_path_str,
                                            f'{exp_name}_{sample_name}_t{t_count}_origin',
                                            'origin',
                                        ])
                                    txt_to_npy(exp_dir_path_str, exp_name,
                                               sample_name, f't{t_count}', 'origin', round(time.time() - st, 6))
                            else:
                                print(
                                    f'Scores of {exp_name}_{sample_name}_t{t_count}_origin.npz exist, should pass')

                        # computing for masking
                        for key in sample_masking_option_keys:
                            paper_data = []
                            feature_masked_npy_file = path.join(
                                exp_dir_path_str, 'scores', f'{exp_name}_{sample_name}_t{t_count}_{key}.npz')
                            if not os.path.exists(feature_masked_npy_file):
                                incomplete_original_npy_file = path.join(
                                    exp_dir_path_str, 'scores', f'{exp_name}_{sample_name}_t{t_count}_{key}#incomplete.txt')
                                if path.exists(incomplete_original_npy_file):
                                    with open(incomplete_original_npy_file) as f:
                                        previous_progress = len(f.readlines())
                                        print(
                                            f'continue computing: {feature_masked_npy_file}')
                                else:
                                    previous_progress = 0
                                    print(
                                        f'start computing: {feature_masked_npy_file}')

                                with open(str(data_file_path)) as f:
                                    line_count = 0
                                    idx = 0
                                    for line in f:
                                        idx += 1
                                        if (idx <= previous_progress):
                                            continue
                                        paper_data.append(json.loads(
                                            line.strip(), strict=False))
                                        line_count += 1
                                        if (line_count == data_loading_line_limit):
                                            paper_data = fm.masking_with_option(
                                                paper_data, fm.masking_options[key])
                                            get_scores_and_save([
                                                sample_query,
                                                paper_data,
                                                exp_dir_path_str,
                                                f'{exp_name}_{sample_name}_t{t_count}_{key}',
                                                key,
                                            ])
                                            paper_data = []
                                            line_count = 0
                                    if len(paper_data) > 0:
                                        paper_data = fm.masking_with_option(
                                            paper_data, fm.masking_options[key])
                                        get_scores_and_save([
                                            sample_query,
                                            paper_data,
                                            exp_dir_path_str,
                                            f'{exp_name}_{sample_name}_t{t_count}_{key}',
                                            key,
                                        ])
                                    txt_to_npy(exp_dir_path_str, exp_name,
                                               sample_name, f't{t_count}', key, round(time.time() - st, 6))
                            else:
                                print(
                                    f'Scores of {exp_name}_{sample_name}_t{t_count}_{key}.npz exist, should pass')

                    print(f'Done with {exp_name} {file_name}')
                print(f'Done with {exp_name}')

            else:
                print(f'\nNo such dir: {str(exp_dir_path)}')
    else:
        print(f'Please provide the name of the experiment data folder.')
