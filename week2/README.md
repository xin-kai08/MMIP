# quiz 1 基礎
使用Breast Cancer Wisconsin(Diagnostic)資料集，根據腫瘤測量特徵預測良性或惡性，將diagnosis做為目標y，M(惡性)=1、B(良性)=0。<br>
使用Logistic Regression實作分類任務。資料共569筆，使用30個數據特徵作為輸入，利用data_segment()做資料切分，training/validation以70%/30%切分，使用stratify=y維持類別比例，random_state=42固定切分結果；在feature_scale()中利用StandardScaler進行特徵標準化；進行模型訓練與驗證後將confusion matrix與輸出指標(accuracy、precision、recall、f1-score)儲存至result資料夾。<br>
調整threshold時，沿用同一個訓練完成的模型，不重新訓練。

### 結果圖
![](./result/quiz1_1/confusion_matrix_0.5.png)
![](./result/quiz1_1/confusion_matrix_0.25.png)


# quiz 1 進階
## 將模型改為Random Forest
設定n_estimators=100、random_state=42，沿用相同的training、validation切分及縮放後的特徵，比較不同threshold跟模型的表現差異。

### 結果圖
![](./result/quiz1_2/confusion_matrix_0.5.png)
![](./result/quiz1_2/confusion_matrix_0.35.png)

## 差異比較
### threshold挑選依據：從0.5出發，以0.1為步距比較f1，改善停止後，額外測試相鄰門檻的中點，最後選擇所有已測試門檻中validation f1最高者
threshold=0.5時，Logistic Regression在recall與f1 score表現較好，accuracy表現與Random Forest相同，而precision表現較差；Logistic Regression有4筆FN、1筆FP，Random Forest有5筆FN、0筆FP，若重視減少漏判惡性，Logistic Regression較好；若重視減少誤報，Random Forest較好。<br>
Logistic Regression表現最好為threshold=0.25時。<br>
Random Forest表現最好為threshold=0.35時。<br>
