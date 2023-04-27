import torch.nn as nn
import torch.nn.functional as F
import timm


class BaseModel(nn.Module):
    def __init__(self, num_classes):
        super().__init__()

        self.conv1 = nn.Conv2d(3, 32, kernel_size=7, stride=1)
        self.conv2 = nn.Conv2d(32, 64, kernel_size=3, stride=1)
        self.conv3 = nn.Conv2d(64, 128, kernel_size=3, stride=1)
        self.dropout1 = nn.Dropout(0.25)
        self.dropout2 = nn.Dropout(0.25)
        self.avgpool = nn.AdaptiveAvgPool2d((1, 1))
        self.fc = nn.Linear(128, num_classes)

    def forward(self, x):
        x = self.conv1(x)
        x = F.relu(x)

        x = self.conv2(x)
        x = F.relu(x)
        x = F.max_pool2d(x, 2)
        x = self.dropout1(x)

        x = self.conv3(x)
        x = F.relu(x)
        x = F.max_pool2d(x, 2)
        x = self.dropout2(x)

        x = self.avgpool(x)
        x = x.view(-1, 128)
        return self.fc(x)


# Custom Model Template
class MyModel(nn.Module):
    def __init__(self, num_classes):
        super().__init__()

        """
        1. ?��??? 같이 ?��?��?��?�� parameter ?�� num_claases �? ?��?��?��주세?��.
        2. ?��만의 모델 ?��?��?��쳐�?? ?��?��?�� ?��봅니?��.
        3. 모델?�� output_dimension ??? num_classes �? ?��?��?��주세?��.
        """

    def forward(self, x):
        """
        1. ?��?��?�� ?��?��?�� 모델 ?��?��?��쳐�?? forward propagation ?�� 진행?��주세?��
        2. 결과�? ?��?�� output ?�� return ?��주세?��
        """
        return x


class VGG19(nn.Module):
    def __init__(self, num_classes):
        super().__init__()

        """
        1. ?��??? 같이 ?��?��?��?�� parameter ?�� num_claases �? ?��?��?��주세?��.
        2. ?��만의 모델 ?��?��?��쳐�?? ?��?��?�� ?��봅니?��.
        3. 모델?�� output_dimension ??? num_classes �? ?��?��?��주세?��.
        """
        self.backbone = vgg19_bn()

        # self.backbone.features.requires_grad_(requires_grad=False) # feature �?분얼리기

        self.backbone.classifier = nn.Sequential(
            nn.Linear(25088, 4096, bias=True),
            nn.ReLU(inplace=True),
            nn.Dropout(p=0.5),
            nn.Linear(4096, 4096, bias=True),
            nn.ReLU(inplace=True),
            nn.Dropout(p=0.5),
            nn.Linear(4096, num_classes, bias=True)
        )

    def forward(self, x):
        """
        1. ?��?��?�� ?��?��?�� 모델 ?��?��?��쳐�?? forward propagation ?�� 진행?��주세?��
        2. 결과�? ?��?�� output ?�� return ?��주세?��
        """
        x = self.backbone(x)
        return x


class vit32(nn.Module):
    def __init__(self, num_classes):
        super().__init__()

        self.backbone = timm.models.vit_base_patch16_224(pretrained=True)

        self.backbone.head = nn.Linear(
            in_features=768, out_features=num_classes, bias=True)

    def forward(self, x):

        x = self.backbone(x)

        return x
