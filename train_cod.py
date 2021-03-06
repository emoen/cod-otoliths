import pandas as pd
import numpy as np
import glob
import os
from pathlib import Path

from sklearn.model_selection import train_test_split
from sklearn import preprocessing
from sklearn.utils import compute_class_weight
from sklearn.metrics import classification_report, confusion_matrix
import scipy

import tensorflow as tf

from tensorflow.keras.callbacks import ModelCheckpoint, TensorBoard, EarlyStopping
from tensorflow.keras.preprocessing.image import img_to_array, load_img, ImageDataGenerator
from tensorflow.keras.layers import Activation, Dense, GlobalAveragePooling2D, GlobalMaxPooling2D
from tensorflow.keras.models import Model
from tensorflow.keras import optimizers
import tensorflow.keras.backend as K

#salmon-scales
from train_util import read_images, load_xy, get_checkpoint_tensorboard, create_model_grayscale, get_fresh_weights, base_output, dense1_linear_output, train_val
idate_test_split


# Error in folder:
# /scratch/disk2/Otoliths/codotoliths_erlend/CodOtholiths-MachineLearning/Savannah_Professional_Practice/2015/70117/nr 04 age_02/IMG_0020.JPG
#_0
#/scratch/disk2/Otoliths/codotoliths_erlend/CodOtholiths-MachineLearning/Savannah_Professional_Practice/2015/70117/Nr03age_02
#/scratch/disk2/Otoliths/codotoliths_erlend/CodOtholiths-MachineLearning/Savannah_Professional_Practice/2015/70331
def read_jpg_cods(B4_input_shape = (380, 380, 3), max_dataset_size = 1985):
    '''
    reads one .jpg file in each folder in structure of folders
    returns tensor with images, and 1-1 correspondence with age
    '''
    #base_dir = '/test123/Savannah_Professional_Practice' #project/cod-otoliths
    #base_dir = '/scratch/disk2/Otoliths/codotoliths_erlend/CodOtholiths-MachineLearning/Savannah_Professional_Practice' #project/cod-otoliths
    base_dir = '/gpfs/gpfs0/deep/data/codotoliths_erlend/'
    dirs = set() # to get just 1 jpg file from each folder
    df_cod = pd.DataFrame(columns=['age', 'path'])

    image_tensor = np.empty(shape=(max_dataset_size,)+B4_input_shape)

    add_count = 0
    base_dirs_posix = Path(base_dir)
    for some_year_dir in base_dirs_posix.iterdir():
        print(some_year_dir)
        if not(some_year_dir.is_dir()):
            break
        for filename in Path(some_year_dir).glob('**/*.JPG'):
            filepath =str(filename)
            dirname = os.path.dirname(filepath)
            if ( dirname not in dirs and os.path.basename(filepath)[0] != '.' ):
                dirs.add(dirname)
                begin_age = filepath.lower().find('age')
                age = filepath[begin_age+3:begin_age+5]
                age = int(age)

                pil_img = load_img(filepath, target_size=B4_input_shape, grayscale=False)
                array_img = img_to_array(pil_img, data_format='channels_last')
                image_tensor[add_count] = array_img
                df_cod = df_cod.append({'age':age, 'path':filepath}, ignore_index=True)
                #df_cod = df_cod.append({'age':age, 'path':filepath+'2'}, ignore_index=True)
                add_count += 1
                #print(add_count)

    age = df_cod.age.values
    return image_tensor, age


def do_train():
    os.environ["CUDA_VISIBLE_DEVICES"]="0"
    tensorboard_path= './tensorboard_test2'
    checkpoint_path = './checkpoints_test2/cod_oto_efficientnetBBB.{epoch:03d}-{val_loss:.2f}.hdf5'
    a_batch_size = 8
    B4_input_shape = (380, 380, 3)
    new_shape = B4_input_shape

    image_tensor, age = read_jpg_cods(B4_input_shape)

    early_stopper = EarlyStopping(patience=40)
    train_datagen = ImageDataGenerator(
        zca_whitening=False,
        width_shift_range=0.2,
        height_shift_range=0.2, #20,
        #zoom_range=[0.5,1.0],
        rotation_range=360,
        horizontal_flip=False,
        vertical_flip=True,
        rescale=1./255)

    train_idx, val_idx, test_idx = train_validate_test_split( range(0, len(image_tensor)) )
    train_rb_imgs = np.empty(shape=(len(train_idx),)+B4_input_shape)
    train_age = []
    for i in range(0, len(train_idx)):
        train_rb_imgs[i] = image_tensor[train_idx[i]]
        train_age.append(age[train_idx[i]])

    val_rb_imgs = np.empty(shape=(len(val_idx),)+B4_input_shape)
    val_age = []
    for i in range(0, len(val_idx)):
        val_rb_imgs[i] = image_tensor[val_idx[i]]
        val_age.append(age[val_idx[i]])

    test_rb_imgs = np.empty(shape=(len(test_idx),)+B4_input_shape)
    test_age = []
    for i in range(0, len(test_idx)):
        test_rb_imgs[i] = image_tensor[test_idx[i]]
        test_age.append(age[test_idx[i]])

    train_age = np.vstack(train_age)
    val_age = np.vstack(val_age)
    test_age = np.vstack(test_age)
    age = np.vstack(age)

    val_rb_imgs = np.multiply(val_rb_imgs, 1./255)
    test_rb_imgs = np.multiply(test_rb_imgs, 1./255)

    rgb_efficientNetB4 = tf.keras.applications.EfficientNetB4(include_top=False, weights='imagenet', input_shape=B4_input_shape, classes=2)
    z = dense1_linear_output( rgb_efficientNetB4 )
    cod = Model(inputs=rgb_efficientNetB4.input, outputs=z)

    learning_rate=0.00005
    adam = optimizers.Adam(learning_rate=learning_rate)

    for layer in cod.layers:
        layer.trainable = True

    def binary_accuracy_for_regression(y_true, y_pred):
        return K.mean(K.equal(y_true, K.round(y_pred)), axis=-1)

    cod.compile(loss='mse', optimizer=adam, metrics=['accuracy','mse', 'mape', binary_accuracy_for_regression] )
    tensorboard, checkpointer = get_checkpoint_tensorboard(tensorboard_path, checkpoint_path)

    classWeight = None

    #Tensorflow 2.2 - wrap generator in tf.data.Dataset
    def callGen():
        return train_datagen.flow(train_rb_imgs, train_age, batch_size=a_batch_size)

    train_dataset = tf.data.Dataset.from_generator(callGen, (tf.float32, tf.float32)).shuffle(128, reshuffle_each_iteration=True).repeat()

    #history_callback = cod.fit(x=image_tensor,y=age, steps_per_epoch=1600, epochs=1)
    #history_callback = cod.fit(callGen(), steps_per_epoch=1600, epochs=1)

    ############## salmon_scales
    new_shape = (380, 380, 3)
    age_cod = age
    rb_imgs, all_sea_age, all_smolt_age, all_farmed_class, all_spawn_class, all_filenames = load_xy()

    uten_ukjent = len(all_sea_age) - all_sea_age.count(-1.0)
    rb_imgs2 = np.empty(shape=(uten_ukjent,)+new_shape)
    unique, counts = np.unique(all_sea_age, return_counts=True)
    print("age distrib:"+str( dict(zip(unique, counts)) ))

    all_sea_age2 = []
    found_count = 0
    all_filenames2 = []
    for i in range(0, len(all_sea_age)):
        if all_sea_age[i] > -1:
            rb_imgs2[found_count] = rb_imgs[i]
            all_sea_age2.append(all_sea_age[i])
            found_count += 1
            all_filenames2.append(all_filenames[i])

    assert found_count == uten_ukjent

    age_scales = all_sea_age2
    rb_imgs = rb_imgs2

    age_scales = np.vstack(age_scales)

    train_datagen_scales = ImageDataGenerator(
        zca_whitening=False,
        width_shift_range=0.2,
        height_shift_range=0.2, #20,
        #zoom_range=[0.5,1.0],
        rotation_range=360,
        horizontal_flip=False,
        vertical_flip=True,
        rescale=1./255)

    train_generator_scales = train_datagen_scales.flow(rb_imgs, age_scales, batch_size= a_batch_size)
    history_callback_scales = cod.fit(train_generator_scales,
        steps_per_epoch=1000,
        epochs=20,
        #callbacks=[early_stopper, tensorboard, checkpointer],
        #validation_data= (val_rb_imgs, val_age),
        class_weight=classWeight)

    ######################


    K.set_value(cod.optimizer.learning_rate, 0.00001)
    print("Learning rate before second fit:", cod.optimizer.learning_rate.numpy())

    history_callback = cod.fit(train_dataset ,
        steps_per_epoch=1600,
        epochs=150,
        callbacks=[early_stopper, tensorboard, checkpointer],
        validation_data= (val_rb_imgs, val_age),
        class_weight=classWeight)

    test_metrics = cod.evaluate(x=test_rb_imgs, y=test_age)
    print("test metric:"+str(cod.metrics_names))
    print("test metrics:"+str(test_metrics))

    print("precision, recall, f1")
    y_pred_test = cod.predict(test_rb_imgs, verbose=1)
    y_pred_test_bool = np.argmax(y_pred_test, axis=1)
    y_true_bool = np.argmax(test_age, axis=1)
    #np.argmax inverse of to_categorical
    argmax_test = np.argmax(test_age, axis=1)
    unique, counts = np.unique(argmax_test, return_counts=True)
    print("test ocurrence of each class:"+str(dict(zip(unique, counts))))

    print("cslassification_report")
    print(classification_report(y_true_bool, y_pred_test_bool))
    print("confusion matrix")
    print(str(confusion_matrix(y_true_bool, y_pred_test_bool)))

def base_output(model):
    z = model.output
    z = GlobalMaxPooling2D()(z)
    return z

def dense1_linear_output(gray_model):
    z = base_output(gray_model)
    z = Dense(1, activation='linear')(z)
    return z

def get_checkpoint_tensorboard(tensorboard_path, checkpoint_path):

    tensorboard = TensorBoard(log_dir=tensorboard_path)
    checkpointer = ModelCheckpoint(
        filepath = checkpoint_path,
        verbose = 1,
        save_best_only = True,
        save_weights_only = False)
    return tensorboard, checkpointer

def train_validate_test_split(pairs, validation_set_size = 0.15, test_set_size = 0.15, a_seed = 8):
    """ split pairs into 3 set, train-, validation-, and test-set
        1 - (validation_set_size + test_set_size) = % training set size
    >>> import pandas as pd
    >>> import numpy as np
    >>> data = np.array([np.arange(10)]*2).T  # 2 columns for x, y, and one for index
    >>> df_ = pd.DataFrame(data, columns=['x', 'y'])
    >>> train_x, val_x, test_x = \
             train_validate_test_split( df_, validation_set_size = 0.2, test_set_size = 0.2, a_seed = 1 )
    >>> train_x['x'].values
    array([0, 3, 1, 7, 8, 5])
    >>> val_x['x'].values
    array([4, 6])
    >>> test_x['x'].values
    array([2, 9])
    """
    validation_and_test_set_size = validation_set_size + test_set_size
    validation_and_test_split = validation_set_size / (test_set_size+validation_set_size)
    df_train_x, df_notTrain_x = train_test_split(pairs, test_size = validation_and_test_set_size, random_state = a_seed)
    df_test_x, df_val_x = train_test_split(df_notTrain_x, test_size = validation_and_test_split, random_state = a_seed)
    return df_train_x, df_val_x, df_test_x

if __name__ == '__main__':
    do_train()
