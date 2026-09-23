# QUIZ 1
使用Kaggle的Vegetable Image Dataset，共有15類，21000張224*224的影像，雖然已經分好train(15000)、validation(3000)、test(3000)資料夾，為了使用k-fold交叉驗證(k=5)，將validation的資料搬回train資料夾。<br>

利用quiz1.py中的def scan_images()將圖片路徑與categories編號配對，再利用5-fold validation將資料切成5等分。<br>

模型輸入為一張蔬菜影像，輸出為該影像屬於各類別的預測分數，並以分數最高的類別作為最終預測，每張影像對應一個類別標籤，因此這是單標籤、多類別分類任務。<br>

資料集共有15個類別，分類目標是讓模型學習各類蔬菜的影像特徵，對未見過的影像正確辨識其類別，後續將以Top-1 Accuracy和Top-5 Accuracy評估分類表現。


# QUIZ 2 基礎
