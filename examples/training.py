import datetime
import os
import sys
import torch
from torch.utils.data import Dataset, DataLoader
from torch import nn
from torchvision import datasets, transforms

from torchvision.transforms import ToTensor
import matplotlib.pyplot as plt

class NeuralNetwork(nn.Module):
    def __init__(self):
        super().__init__()
        self.flatten = nn.Flatten()
        self.linear_relu_stack = nn.Sequential(
            nn.Linear(28*28, 512),
            nn.ReLU(),
            nn.Linear(512, 512),
            nn.ReLU(),
            nn.Linear(512, 10),
        )

    def forward(self, x):
        x = self.flatten(x)
        logits = self.linear_relu_stack(x)
        return logits



def train_loop(dataloader, model, loss_fn, optimizer, device):
    size = len(dataloader.dataset)
    # Set the model to training mode - important for batch normalization and dropout layers
    # Unnecessary in this situation but added for best practices
    model.train()
    for batch, (X, y) in enumerate(dataloader):
        # Compute prediction and loss
        d_X = X.to(device)
        d_y = y.to(device)
        pred = model(d_X)
        loss = loss_fn(pred, d_y)

        # Backpropagation
        loss.backward()
        optimizer.step()
        optimizer.zero_grad()

        if batch % 100 == 0:
            loss, current = loss.item(), batch * batch_size + len(X)
            print(f"loss: {loss:>7f}  [{current:>5d}/{size:>5d}]")


def test_loop(dataloader, model, loss_fn, device):
    # Set the model to evaluation mode - important for batch normalization and dropout layers
    # Unnecessary in this situation but added for best practices
    model.eval()
    size = len(dataloader.dataset)
    num_batches = len(dataloader)
    test_loss, correct = 0, 0

    # Evaluating the model with torch.no_grad() ensures that no gradients are computed during test mode
    # also serves to reduce unnecessary gradient computations and memory usage for tensors with requires_grad=True
    with torch.no_grad():
        for X, y in dataloader:
            d_X = X.to(device)
            d_y = y.to(device)
            pred = model(d_X)
            test_loss += loss_fn(pred, d_y).item()
            correct += (pred.argmax(1) == d_y).type(torch.float).sum().item()

    test_loss /= num_batches
    correct /= size
    print(f"Test Error: \n Accuracy: {(100*correct):>0.1f}%, Avg loss: {test_loss:>8f} \n")

if __name__ == "__main__":

    device_id = 0
    if len(sys.argv) >= 2:
        device_id = int(sys.argv[1])

    learning_rate = 1e-3
    batch_size = 64
    epochs = 5

    download_data = True
    training_data = datasets.FashionMNIST(
        root="data",
        train=True,
        download=download_data,
        transform=ToTensor()
    )

    test_data = datasets.FashionMNIST(
        root="data",
        train=False,
        download=download_data,
        transform=ToTensor()
    )


    train_dataloader = DataLoader(training_data, batch_size=batch_size, shuffle=True)
    test_dataloader = DataLoader(test_data, batch_size=batch_size, shuffle=True)

    device = (
        "cuda"
        if torch.cuda.is_available()
        else "mps"
        if torch.backends.mps.is_available()
        else "cpu"
    )

    model = NeuralNetwork()

    if device == "cuda":
        print(f"Using {device} device")
        num_devices = torch.cuda.device_count()
        torch.cuda.set_device(device_id)
        current_dev = torch.cuda.current_device()
        device_name = torch.cuda.get_device_name()
        cc = torch.cuda.get_device_capability()

        print(f"Visible device count: {num_devices}")
        print(f"Current device: [{current_dev}] {device_name} compute capability {cc}")

        model = model.to(device)
        
    print(model)


    loss_fn = nn.CrossEntropyLoss()
    optimizer = torch.optim.SGD(model.parameters(), lr=learning_rate)

    epochs = 10
    for t in range(epochs):
        print(f"Epoch {t+1}\n-------------------------------")
        train_loop(train_dataloader, model, loss_fn, optimizer, device)
        test_loop(test_dataloader, model, loss_fn, device)
    print("Done!")

    dmy = datetime.datetime.now()
    date = dmy.strftime("%d%b%y")
    model_version=f"model-{date}.pkl"
    torch.save(model.state_dict(), model_version)
