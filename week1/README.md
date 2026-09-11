# quiz 1 基礎
用OpenCV讀入dataset資料夾中的圖，直接將讀入的BGR圖片轉成灰階，再用Matplotlib顯示結果，並存入result資料夾
### 比較圖
![](./result/quiz1_1.jpg)


# quiz 1 進階
## 用numpy與雙層for loop實作灰階轉換，在quiz1.py中建立def grayscale_mean(image)函式
先將image的height與width讀取，建立全零的二維矩陣gray_image，大小為(height, width)，再將image每piexl中的RGB值取出，先轉為整數避免相加時溢位，計算三者的算術平均數，將結果填入gray_image的對應位置
### 比較圖
![](./result/quiz1_2.jpg)

## 差異比較
執行速度：OpenCV的轉換速度明顯高於numpy自行實作，因為OpenCV利用底層編譯好的C++程式進行影像轉換，而自行實作使用for loop處理每pixel，每次都需進行陣列存取、型別轉換與數值運算。本實驗結果不能認為加權平均比算術平均快

轉換結果：OpenCV使用的是加權平均轉換成灰階圖，自行實作是使用算術平均，因此部分灰階亮度不同


# quiz 2 基礎
用OpenCV對灰階圖做histogram equalization，並分別統計處理前後各灰階值的影像數量，再用Matplotlib顯示結果，並存入result資料夾
### 比較圖
![](./result/quiz2_1.jpg)

# quiz 2 進階
## 用numpy實作histogram equalization，在quiz2.py中建立def equalized_numpy(image)函式
建立長度為256的histogram陣列，統計每個灰階值出現次數，利用均衡化公式將範圍投影至0~255，建立新舊灰階值的對照表
### 比較圖
![](./result/quiz2_2.png)

## 差異比較
執行速度：OpenCV的轉換速度明顯高於numpy自行實作，因為OpenCV透過底層編譯並最佳化的程式執行，而自行實作的方法使用for loop逐像素統計與查表。本實驗結果主要反映實作方式的差異，不能認為numpy的所有用法都較慢

轉換結果：兩種方法使用相同原理的直方圖均衡化，預期會得到相近的亮度分布與對比效果