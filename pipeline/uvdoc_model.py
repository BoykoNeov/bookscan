"""UVDoc network + unwarping helpers — VENDORED from the official UVDoc repo.

Source: https://github.com/tanguymagne/UVDoc  (model.py, utils.py)
Paper:  "UVDoc: Neural Grid-based Document Unwarping", Verhoeven, Magne, Sorkine-
        Hornung, SIGGRAPH Asia 2023 — https://arxiv.org/abs/2302.02887
License: MIT (see the upstream repo LICENSE). Vendored verbatim (network) so the
pipeline has no external clone dependency; only torch is required at runtime.

The pretrained checkpoint (``best_model.pkl``, ~32 MB, ``{"model_state": ...}``)
is NOT vendored — it is downloaded into ``models/uvdoc/`` (gitignored) and loaded
with ``weights_only=True`` (the checkpoint is a pure tensor state_dict, so this
avoids executing pickle from a downloaded file).

Inference contract this file preserves (why UVDoc satisfies CLAUDE.md's full-res
requirement): the net predicts a LOW-RES 2D sampling grid from a 488x712 input,
but ``bilinear_unwarping`` upsamples that grid to the ORIGINAL page size and runs
``grid_sample`` on the FULL-RES image — so the dewarped output is full resolution
(Stage 06 patch crops come from it), never a downscaled copy.
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

# Network input size (w, h) the checkpoint was trained at.
IMG_SIZE = [488, 712]


def conv3x3(in_channels, out_channels, kernel_size, stride=1):
    return nn.Conv2d(
        in_channels, out_channels, kernel_size=kernel_size, stride=stride,
        padding=kernel_size // 2,
    )


def dilated_conv_bn_act(in_channels, out_channels, act_fn, BatchNorm, dilation):
    return nn.Sequential(
        nn.Conv2d(in_channels, out_channels, bias=False, kernel_size=3, stride=1,
                  padding=dilation, dilation=dilation),
        BatchNorm(out_channels),
        act_fn,
    )


def dilated_conv(in_channels, out_channels, kernel_size, dilation, stride=1):
    return nn.Sequential(
        nn.Conv2d(in_channels, out_channels, kernel_size=kernel_size, stride=stride,
                  padding=dilation * (kernel_size // 2), dilation=dilation)
    )


class ResidualBlockWithDilation(nn.Module):
    def __init__(self, in_channels, out_channels, BatchNorm, kernel_size, stride=1,
                 downsample=None, is_activation=True, is_top=False):
        super().__init__()
        self.stride = stride
        self.downsample = downsample
        self.is_activation = is_activation
        self.is_top = is_top
        if self.stride != 1 or self.is_top:
            self.conv1 = conv3x3(in_channels, out_channels, kernel_size, self.stride)
            self.conv2 = conv3x3(out_channels, out_channels, kernel_size)
        else:
            self.conv1 = dilated_conv(in_channels, out_channels, kernel_size, dilation=3)
            self.conv2 = dilated_conv(out_channels, out_channels, kernel_size, dilation=3)
        self.bn1 = BatchNorm(out_channels)
        self.relu = nn.ReLU(inplace=True)
        self.bn2 = BatchNorm(out_channels)

    def forward(self, x):
        residual = x
        if self.downsample is not None:
            residual = self.downsample(x)
        out1 = self.relu(self.bn1(self.conv1(x)))
        out2 = self.bn2(self.conv2(out1))
        out2 += residual
        return self.relu(out2)


class ResnetStraight(nn.Module):
    def __init__(self, num_filter, map_num, BatchNorm, block_nums=[3, 4, 6, 3],
                 block=ResidualBlockWithDilation, kernel_size=5, stride=[1, 1, 2, 2]):
        super().__init__()
        self.in_channels = num_filter * map_num[0]
        self.stride = stride
        self.relu = nn.ReLU(inplace=True)
        self.block_nums = block_nums
        self.kernel_size = kernel_size
        self.layer1 = self.blocklayer(block, num_filter * map_num[0], block_nums[0],
                                      BatchNorm, kernel_size, self.stride[0])
        self.layer2 = self.blocklayer(block, num_filter * map_num[1], block_nums[1],
                                      BatchNorm, kernel_size, self.stride[1])
        self.layer3 = self.blocklayer(block, num_filter * map_num[2], block_nums[2],
                                      BatchNorm, kernel_size, self.stride[2])

    def blocklayer(self, block, out_channels, block_nums, BatchNorm, kernel_size, stride=1):
        downsample = None
        if (stride != 1) or (self.in_channels != out_channels):
            downsample = nn.Sequential(
                conv3x3(self.in_channels, out_channels, kernel_size=kernel_size, stride=stride),
                BatchNorm(out_channels),
            )
        layers = [block(self.in_channels, out_channels, BatchNorm, kernel_size, stride,
                        downsample, is_top=True)]
        self.in_channels = out_channels
        for _ in range(1, block_nums):
            layers.append(block(out_channels, out_channels, BatchNorm, kernel_size,
                                is_activation=True, is_top=False))
        return nn.Sequential(*layers)

    def forward(self, x):
        return self.layer3(self.layer2(self.layer1(x)))


class UVDocnet(nn.Module):
    def __init__(self, num_filter, kernel_size=5):
        super().__init__()
        self.num_filter = num_filter
        self.in_channels = 3
        self.kernel_size = kernel_size
        self.stride = [1, 2, 2, 2]
        BatchNorm = nn.BatchNorm2d
        act_fn = nn.ReLU(inplace=True)
        map_num = [1, 2, 4, 8, 16]

        self.resnet_head = nn.Sequential(
            nn.Conv2d(self.in_channels, num_filter * map_num[0], bias=False,
                      kernel_size=kernel_size, stride=2, padding=kernel_size // 2),
            BatchNorm(num_filter * map_num[0]), act_fn,
            nn.Conv2d(num_filter * map_num[0], num_filter * map_num[0], bias=False,
                      kernel_size=kernel_size, stride=2, padding=kernel_size // 2),
            BatchNorm(num_filter * map_num[0]), act_fn,
        )
        self.resnet_down = ResnetStraight(
            num_filter, map_num, BatchNorm, block_nums=[3, 4, 6, 3],
            block=ResidualBlockWithDilation, kernel_size=kernel_size, stride=self.stride,
        )
        i = 2
        self.bridge_1 = nn.Sequential(dilated_conv_bn_act(num_filter * map_num[i], num_filter * map_num[i], act_fn, BatchNorm, 1))
        self.bridge_2 = nn.Sequential(dilated_conv_bn_act(num_filter * map_num[i], num_filter * map_num[i], act_fn, BatchNorm, 2))
        self.bridge_3 = nn.Sequential(dilated_conv_bn_act(num_filter * map_num[i], num_filter * map_num[i], act_fn, BatchNorm, 5))
        self.bridge_4 = nn.Sequential(*[dilated_conv_bn_act(num_filter * map_num[i], num_filter * map_num[i], act_fn, BatchNorm, d) for d in [8, 3, 2]])
        self.bridge_5 = nn.Sequential(*[dilated_conv_bn_act(num_filter * map_num[i], num_filter * map_num[i], act_fn, BatchNorm, d) for d in [12, 7, 4]])
        self.bridge_6 = nn.Sequential(*[dilated_conv_bn_act(num_filter * map_num[i], num_filter * map_num[i], act_fn, BatchNorm, d) for d in [18, 12, 6]])
        self.bridge_concat = nn.Sequential(
            nn.Conv2d(num_filter * map_num[i] * 6, num_filter * map_num[2], bias=False,
                      kernel_size=1, stride=1, padding=0),
            BatchNorm(num_filter * map_num[2]), act_fn,
        )
        self.out_point_positions2D = nn.Sequential(
            nn.Conv2d(num_filter * map_num[2], num_filter * map_num[0], bias=False,
                      kernel_size=kernel_size, stride=1, padding=kernel_size // 2, padding_mode="reflect"),
            BatchNorm(num_filter * map_num[0]), nn.PReLU(),
            nn.Conv2d(num_filter * map_num[0], 2, kernel_size=kernel_size, stride=1,
                      padding=kernel_size // 2, padding_mode="reflect"),
        )
        self.out_point_positions3D = nn.Sequential(
            nn.Conv2d(num_filter * map_num[2], num_filter * map_num[0], bias=False,
                      kernel_size=kernel_size, stride=1, padding=kernel_size // 2, padding_mode="reflect"),
            BatchNorm(num_filter * map_num[0]), nn.PReLU(),
            nn.Conv2d(num_filter * map_num[0], 3, kernel_size=kernel_size, stride=1,
                      padding=kernel_size // 2, padding_mode="reflect"),
        )
        self._initialize_weights()

    def _initialize_weights(self):
        for m in self.modules():
            if isinstance(m, (nn.Conv2d, nn.ConvTranspose2d)):
                nn.init.xavier_normal_(m.weight, gain=0.2)

    def forward(self, x):
        resnet_head = self.resnet_head(x)
        resnet_down = self.resnet_down(resnet_head)
        bridge = self.bridge_concat(torch.cat([
            self.bridge_1(resnet_down), self.bridge_2(resnet_down),
            self.bridge_3(resnet_down), self.bridge_4(resnet_down),
            self.bridge_5(resnet_down), self.bridge_6(resnet_down),
        ], dim=1))
        return self.out_point_positions2D(bridge), self.out_point_positions3D(bridge)


def load_model(ckpt_path):
    """Build UVDocnet and load the pretrained state. ``weights_only=True``: the
    checkpoint is a pure tensor state_dict, so no pickle code is executed."""
    model = UVDocnet(num_filter=32, kernel_size=5)
    ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=True)
    model.load_state_dict(ckpt["model_state"])
    return model


def bilinear_unwarping(warped_img, point_positions, img_size):
    """Unwarp ``warped_img`` (BxCxHxW) by the 2D grid ``point_positions``
    (Bx2xGhxGw). The grid is upsampled to the FULL image size, so grid_sample
    runs on the full-resolution page. ``img_size`` = (w, h)."""
    upsampled_grid = F.interpolate(
        point_positions, size=(img_size[1], img_size[0]), mode="bilinear", align_corners=True
    )
    return F.grid_sample(
        warped_img, upsampled_grid.transpose(1, 2).transpose(2, 3), align_corners=True
    )
