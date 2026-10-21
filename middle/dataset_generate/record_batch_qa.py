"""Record an actual visual check without approving a generated image."""
import argparse
import waste_workflow as w

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('task_id')
    p.add_argument('notes')
    p.add_argument('--effective-prompt')
    a = p.parse_args()
    with w.lock():
        tasks, task = w.get_task(a.task_id)
        if task['status'] != 'success':
            raise ValueError('Save the generated output before recording QA')
        qa_file = w.WORK / 'balance_visual_qa.json'
        qa = w.read_json(qa_file, [])
        if any(q['task_id'] == a.task_id for q in qa):
            raise ValueError('Already visually checked; preserve subsequent manual labels')
        evidence = dict(task_id=a.task_id, image_path=task['output_path'],
                        source_path=task['source_path'], observed_residual='food',
                        observed_pooled_liquid=False, review_status='pending',
                        reviewer='assistant_visual_review', notes=a.notes, at=w.now())
        if a.effective_prompt:
            task['effective_prompt'] = a.effective_prompt
            w.atomic_json(w.WORK / 'generation_tasks.json', tasks)
            evidence['effective_prompt'] = a.effective_prompt
        qa.append(evidence)
        w.atomic_json(qa_file, qa)
        w.event('visual_qa_pending_human', **evidence)
        w.annotate([dict(image_path=task['output_path'], residual_applicable='yes',
                         residual='food', review_status='pending',
                         visual_review_by='assistant_visual_review',
                         notes='實際看圖初標：食物殘留，未見明顯積液；待人工複核。' + a.notes)])
        w.write_csv(w.WORK / 'reports' / 'balance_visual_qa.csv', qa)
