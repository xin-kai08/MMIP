"""Explicit four-class metrics, including zero support classes."""
def classification_metrics(targets, predictions, classes, loss_sum=0.):
    matrix=[[0]*len(classes) for _ in classes]
    for a,b in zip(targets,predictions): matrix[a][b]+=1
    reports=[]
    for i,name in enumerate(classes):
        tp=matrix[i][i];support=sum(matrix[i]);predicted=sum(row[i] for row in matrix)
        precision=tp/predicted if predicted else 0.;recall=tp/support if support else 0.
        f1=2*precision*recall/(precision+recall) if precision+recall else 0.
        reports.append(dict(label=name,precision=precision,recall=recall,f1=f1,support=support))
    n=len(targets)
    return dict(n=n,loss=loss_sum/n if n else None,accuracy=sum(matrix[i][i] for i in range(len(classes)))/n if n else None,
                macro_f1=sum(x['f1'] for x in reports)/len(classes) if n else None,
                per_class=reports,confusion_matrix=matrix,classes=classes)
