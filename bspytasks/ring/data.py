"""
Created on Thu Aug 27 2020
This file contains classes related to the ring data generation and loading. 
@author: Unai Alegre-Ibarra
"""
import os
import torch
import numpy as np

from torch.utils.data import Dataset, Sampler
from torch.utils.data import random_split, SubsetRandomSampler


class RingDatasetGenerator(Dataset):
    def __init__(self, sample_no, gap, transforms=None, save_dir=None, verbose=True):
        # The gap needs to be in a scale from -1 to 1.
        # The sample_no is related to the data that is going to be generated but it actually gets reduced when filtering the circles
        # TODO: Make the dataset generate the exact number of samples as requested by the user
        self.transforms = transforms
        self.inputs, self.targets = self.generate_data(sample_no, gap, verbose=verbose)
        self.gap = gap
        assert len(self.inputs) == len(
            self.targets
        ), "Targets and inputs must have the same length"

        if save_dir is not None:
            np.savez(
                os.path.join(save_dir, "input_data_gap_" + str(gap)),
                gap=gap,
                inputs=self.inputs,
                targets=self.targets,
            )
            # TODO: Save a plot of the data

    def __len__(self):
        return len(self.inputs)

    def __getitem__(self, index):
        sample = (self.inputs[index, :], self.targets[index, :])

        if self.transforms is not None:
            sample = self.transforms(sample)

        return sample

    def generate_data(self, sample_no, gap, verbose=True):
        assert sample_no % 2 == 0, "Only an even sample number is supported."
        indices = self.get_balanced_distribution_indices(sample_no)
        sample_no = int(sample_no / 2)
        limit = (1 - gap) / 2
        class0_points = self.get_class_points(sample_no, 0, limit)
        class0_targets = np.zeros(sample_no)
        class1_points = self.get_class_points(sample_no, 1 - limit, 1)
        class1_targets = np.ones(sample_no)
        points = np.vstack((class0_points, class1_points))
        targets = np.hstack((class0_targets, class1_targets))[:, np.newaxis]

        if verbose:
            print(f"There are a total of {len(points)} samples")
            print(f"The input ring dataset has a {gap} gap (In a range from -1 to 1).")

        return points[indices], targets[indices]

    def get_class_points(self, sample_no, in_limit, out_limit):
        # Create a straight line with the size of the dataset
        linspace_out = np.linspace(0, 2 * np.pi, sample_no, endpoint=False)
        linspace_in = np.linspace(0, 2 * np.pi, sample_no, endpoint=False)

        # Create the limits of the area in which the points are generated
        outer_circ_x = np.cos(linspace_out) * out_limit
        outer_circ_y = np.sin(linspace_out) * out_limit
        inner_circ_x = np.cos(linspace_in) * in_limit
        inner_circ_y = np.sin(linspace_in) * in_limit

        # Get uniformly distributed samples within the limits
        x = np.random.uniform(low=inner_circ_x, high=outer_circ_x, size=(sample_no,))
        y = np.random.uniform(low=inner_circ_y, high=outer_circ_y, size=(sample_no,))

        return np.vstack((x, y)).T

    def get_balanced_distribution_indices(self, data_length):
        permuted_indices = np.random.permutation(data_length)
        class0 = permuted_indices[permuted_indices < int(data_length / 2)]
        class1 = permuted_indices[permuted_indices >= int(data_length / 2)]
        assert len(class0) == len(
            class1
        ), "Sampler only supports datasets with an even class distribution"
        result = []
        for i in range(len(class0)):
            result.append(class0[i])
            result.append(class1[i])
        return np.array(result)


class RingDatasetLoader(Dataset):
    def __init__(self, file_path, transforms=None, save_dir=None, verbose=True):

        data = np.load(file_path)
        self.inputs, self.targets = data["inputs"], data["targets"]
        self.gap = data["gap"]
        self.transforms = transforms
        assert len(self.inputs) == len(
            self.targets
        ), "Targets and inputs must have the same length"
        if verbose:
            print(
                f"There are a total of {len(self.inputs[self.targets == 0]) + len(self.inputs[self.targets == 1])} samples"
            )
            print(
                f"The input ring dataset has a {self.gap} gap (In a range from -1 to 1)."
            )

    def __len__(self):
        return len(self.inputs)

    def __getitem__(self, index):
        sample = (self.inputs[index, :], self.targets[index, :])

        if self.transforms is not None:
            sample = self.transforms(sample)

        return sample


class BalancedSubsetRandomSampler(Sampler):
    r"""Samples elements randomly from a given list of indices, without replacement.

    Arguments:
        indices (sequence): a sequence of indices
    """

    def __init__(self, indices, generator=None):
        super().__init__(indices)
        self.indices = indices
        self.generator = generator

    def __iter__(self):
        return (self.indices[i] for i in balanced_permutation(len(self.indices)))

    def __len__(self):
        return len(self.indices)


def split(
    dataset,
    batch_size,
    num_workers,
    sampler=SubsetRandomSampler,
    split_percentages=[0.8, 0.1, 0.1],
    pin_memory=True
):
    # Split percentages are expected to be in the following format: [80,10,10]
    percentages = np.array(split_percentages)
    assert np.sum(percentages) == 1, "Split percentage does not sum up to 1"
    indices = list(range(len(dataset)))
    indices = balanced_permutation(len(dataset))
    max_train_index = int(np.floor(percentages[0] * len(dataset)))
    max_dev_index = int(np.floor((percentages[0] + percentages[1]) * len(dataset)))
    max_test_index = int(np.floor(np.sum(percentages) * len(dataset)))

    train_index = indices[:max_train_index]
    dev_index = indices[max_train_index:max_dev_index]
    test_index = indices[max_dev_index:max_test_index]

    train_sampler = sampler(train_index)
    dev_sampler = sampler(dev_index)
    test_sampler = sampler(test_index)
    if batch_size > 0:
        batch_size = [batch_size, batch_size, batch_size]
    else:

        batch_size = [
            get_batch_size(train_sampler),
            get_batch_size(dev_sampler),
            get_batch_size(test_sampler),
        ]
    train_loader = torch.utils.data.DataLoader(
        dataset,
        batch_size=batch_size[0],
        sampler=train_sampler,
        num_workers=num_workers,
        pin_memory=pin_memory
    )
    dev_loader = torch.utils.data.DataLoader(
        dataset, batch_size=batch_size[1], sampler=dev_sampler, num_workers=num_workers, pin_memory=pin_memory
    )
    test_loader = torch.utils.data.DataLoader(
        dataset, batch_size=batch_size[2], sampler=test_sampler, num_workers=num_workers, pin_memory=pin_memory
    )

    return [
        train_loader,
        dev_loader,
        test_loader,
    ]  # , [train_index, dev_index, test_loader]
    # lengths = [int(len(dataset) * split_percentages[0]), int(len(dataset) * split_percentages[1]), int(len(dataset) * split_percentages[2])]
    # datasets = random_split(dataset, lengths)
    # samplers = [sampler(ds.indices) for ds in datasets]

    # return [torch.utils.data.DataLoader(datasets[i], sampler=samplers[i], batch_size=batch_size, num_workers=num_workers) for i in range(len(datasets))]


def get_batch_size(sampler):
    if len(sampler) > 0:
        return len(sampler)
    else:
        return 1


def balanced_permutation(len_indices):
    permuted_indices = torch.randperm(len_indices)
    class0 = permuted_indices[permuted_indices % 2 == 0]
    class1 = permuted_indices[permuted_indices % 2 == 1]
    assert len(class0) == len(
        class1
    ), "Sampler only supports datasets with an even class distribution"
    result = []
    for i in range(len(class0)):
        result.append(class0[i])
        result.append(class1[i])
    return torch.tensor(result, dtype=torch.int64)
