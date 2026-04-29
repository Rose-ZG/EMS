# train_model.py
from ultralytics import YOLO

def main():
    # 自动识别设备：有GPU用GPU，没有用CPU
    import torch
    device = 0 if torch.cuda.is_available() else 'cpu'
    print(f"当前正在使用设备: {device}")

    model = YOLO('yolov8n-pose.pt')

    results = model.train(
        data='datasets/data.yaml',
        epochs=50,
        imgsz=640,
        device=device,              # 自动指向显卡
        batch=16,                   # 4060显存大，可以一次跑16张，速度更快
        project='runs/pose',
        name='fall_detect',
        plots=True,
        # degrees = 15.0,  # 随机旋转正负15度
        # flipud = 0.5,  # 增加上下翻转（模拟从不同视角看跌倒）
        # mosaic = 1.0,  # 马赛克增强
    )

if __name__ == '__main__':
    main()