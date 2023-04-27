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
        1. ???? κ°μ΄ ??±?? parameter ? num_claases λ₯? ?¬?¨?΄μ£ΌμΈ?.
        2. ?λ§μ λͺ¨λΈ ??€?μ³λ?? ???Έ ?΄λ΄λ?€.
        3. λͺ¨λΈ? output_dimension ??? num_classes λ‘? ?€? ?΄μ£ΌμΈ?.
        """

    def forward(self, x):
        """
        1. ??? ? ?? λͺ¨λΈ ??€?μ³λ?? forward propagation ? μ§ν?΄μ£ΌμΈ?
        2. κ²°κ³Όλ‘? ??¨ output ? return ?΄μ£ΌμΈ?
        """
        return x


class VGG19(nn.Module):
    def __init__(self, num_classes):
        super().__init__()

        """
        1. ???? κ°μ΄ ??±?? parameter ? num_claases λ₯? ?¬?¨?΄μ£ΌμΈ?.
        2. ?λ§μ λͺ¨λΈ ??€?μ³λ?? ???Έ ?΄λ΄λ?€.
        3. λͺ¨λΈ? output_dimension ??? num_classes λ‘? ?€? ?΄μ£ΌμΈ?.
        """
        self.backbone = vgg19_bn()

        # self.backbone.features.requires_grad_(requires_grad=False) # feature λΆ?λΆμΌλ¦¬κΈ°

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
        1. ??? ? ?? λͺ¨λΈ ??€?μ³λ?? forward propagation ? μ§ν?΄μ£ΌμΈ?
        2. κ²°κ³Όλ‘? ??¨ output ? return ?΄μ£ΌμΈ?
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
