# quiz 1
## Sentiment Analysis使用IMDB Dataset of 50K Movie Reviews資料集
確認CSV欄位為review、sentiment，共50,000筆，正負面各25,000筆。<br>
檢查缺失值與空白影評，皆為0；找到418筆額外重複影評，且相同影評沒有label衝突。

## Image Classification使用Rock-Paper-Scissors Images資料集
統計各類圖片數量，逐張讀取，確認沒有讀取失敗，圖片皆為RGB、300 * 200。<br>
每類抽樣一張確認內容符合label，並透過圖片內容的SHA-256 hash檢查，未找到完全相同的圖片。

## Image Captioning使用Flickr 8k Dataset資料集
確認有8,091張圖片、40,455筆captions，每張對應5筆，缺失值、空白檔名與空白caption皆為 0，圖片檔名與caption表格皆能互相對應。<br>
圖片全部可讀取、皆為RGB，圖片尺寸多不相同。抽樣確認圖片符合captions，找到10筆額外重複image-caption配對，以及1張額外重複圖片。


# quiz 2 基礎
將IMDB Dataset of 50K Movie Reviews資料以80%、10%、10%分成train、validation、test。<br>
利用tokenize()移除HTML tags、轉小寫，取出英文單字。<br>
利用build_vocab()統計train dataset詞頻，收錄最多的20,000個tokens。<br>
利用text_to_ids()將tokens查表轉換成IDs，未收錄的詞用`<UNK>`。<br>
利用collate_reviews()將sequence補PAD至該batch最長sequence。<br>
模型架構方面，輸入為128維embedding，連接至單層單向RNN(hidden size=128)，最後用linear分類層輸出兩類logits。<br>
使用batch size=32、Cross-Entropy Loss、Adam、learning rate=0.001、dropout=0.3、gradient clipping=1.0、early stopping，以及pack_padded_sequence()，讓RNN跳過補位位置。

### 結果圖
<img src="./results/rnn/training_curves.png" width="900">
<img src="./results/rnn/confusion_matrix.png" width="600">


# quiz 2 進階
## 沿用quiz 2基礎的流程，更換為LSTM模型
模型架構一樣為輸入128維embedding，連接單層單向LSTM(hidden size=128)，最後用linear分類層輸出兩類logits。<br>
loss function、optimizer等等都與RNN相同。

### 結果圖
<img src="./results/lstm/training_curves.png" width="900">
<img src="./results/lstm/confusion_matrix.png" width="600">

## 結論
由結果可以看出，在相同架構下，LSTM的test loss、accuracy、macro f1-score都比RNN表現要好，從混淆矩陣上也可以看出LSTM表現較好，但兩個模型都有嚴重的overfitting。


# quiz 3 基礎
利用prepare_splits()將Rock-Paper-Scissors Images資料以80%、10%、10%分成train、validation、test，並設定rock=0、paper=1、scissors=2。<br>
使用create_vit()載入timm，取得ViT的輸入設定，將圖片轉成RGB、調整尺寸、轉成tensor並normalize，並加入隨機裁切、水平翻轉和色彩變化。<br>
模型架構方面，使用pretrained ViT-Tiny，將輸出改為三類，凍結backbone只訓練最後的分類層。<br>
使用batch size=32、Cross-Entropy Loss、AdamW、learning rate=0.001、weight decay=0.01、early stopping。

### 結果圖
<img src="./results/vit/training_curves.png" width="900">
<img src="./results/vit/roc_curves.png" width="600">


# quiz 3 進階
## 沿用quiz 3基礎的流程，更換為ResNet-18模型
模型架構一樣為凍結backbone，將輸出改為三類，只訓練最後的分類層。<br>
loss function、optimizer等等都與ViT相同。

### 結果圖
<img src="./results/resnet/training_curves.png" width="900">
<img src="./results/resnet/roc_curves.png" width="600">

## 結論
由loss和accuracy curve可以看出ViT在訓練時比較穩定，並且test loss與macro f1-score也比ResNet-18好上不少，雖然ResNet-18表現看似比ViT差上不少，但兩者在macro AUC皆表現優異。


# quiz 4 基礎