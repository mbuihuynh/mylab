



#from keras_contrib.layers.normalization import InstanceNormalization
from tensorflow.keras.layers import Input, Dense, Reshape, Flatten, Dropout, Concatenate
from tensorflow.keras.layers import BatchNormalization, Activation, ZeroPadding2D
from tensorflow.keras.layers import LeakyReLU
from tensorflow.keras.layers import UpSampling2D, Conv2D
from tensorflow.keras.models import Sequential, Model
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.models import model_from_json
import datetime
import matplotlib.pyplot as plt
#from data_loader import DataLoader
import numpy as np
import os

from glob import glob

class Pix2Pix():
    def __init__(self):
        # Input shape
        self.img_rows = 256
        self.img_cols = 256
        self.channels = 3
        self.img_shape = (self.img_rows, self.img_cols, self.channels)

        # Configure data loader
        self.dataset_name = 'breakhis'
        #self.data_loader = DataLoader(dataset_name=self.dataset_name,
        #                              img_res=(self.img_rows, self.img_cols))

        # Calculate output shape of D (PatchGAN)
        patch = int(self.img_rows / 2**4)
        self.disc_patch = (patch, patch, 1)

        # Number of filters in the first layer of G and D
        self.gf = 64
        self.df = 64

        optimizer = Adam(0.0002, 0.5)

        # Build and compile the discriminator
        self.discriminator = self.build_discriminator()
        self.discriminator.compile(loss='mse',
            optimizer=optimizer,
            metrics=['accuracy'])

        #-------------------------
        # Construct Computational
        #   Graph of Generator
        #-------------------------

        # Build the generator
        self.generator = self.build_generator()

        # Input images and their conditioning images
        img_A = Input(shape=self.img_shape)
        img_B = Input(shape=self.img_shape)

        # By conditioning on B generate a fake version of A
        fake_A = self.generator(img_B)

        # For the combined model we will only train the generator
        self.discriminator.trainable = False

        # Discriminators determines validity of translated images / condition pairs
        valid = self.discriminator([fake_A, img_B])

        self.combined = Model(inputs=[img_A, img_B], outputs=[valid, fake_A])
        self.combined.compile(loss=['mse', 'mae'],
                              loss_weights=[1, 100],
                              optimizer=optimizer)

    def build_generator(self):
        """U-Net Generator"""

        def conv2d(layer_input, filters, f_size=4, bn=True):
            """Layers used during downsampling"""
            d = Conv2D(filters, kernel_size=f_size, strides=2, padding='same')(layer_input)
            d = LeakyReLU(alpha=0.2)(d)
            if bn:
                d = BatchNormalization(momentum=0.8)(d)
            return d

        def deconv2d(layer_input, skip_input, filters, f_size=4, dropout_rate=0):
            """Layers used during upsampling"""
            u = UpSampling2D(size=2)(layer_input)
            u = Conv2D(filters, kernel_size=f_size, strides=1, padding='same', activation='relu')(u)
            if dropout_rate:
                u = Dropout(dropout_rate)(u)
            u = BatchNormalization(momentum=0.8)(u)
            u = Concatenate()([u, skip_input])
            return u

        # Image input
        d0 = Input(shape=self.img_shape)

        # Downsampling
        d1 = conv2d(d0, self.gf, bn=False)
        d2 = conv2d(d1, self.gf*2)
        d3 = conv2d(d2, self.gf*4)
        d4 = conv2d(d3, self.gf*8)
        d5 = conv2d(d4, self.gf*8)
        d6 = conv2d(d5, self.gf*8)
        d7 = conv2d(d6, self.gf*8)

        # Upsampling
        u1 = deconv2d(d7, d6, self.gf*8)
        u2 = deconv2d(u1, d5, self.gf*8)
        u3 = deconv2d(u2, d4, self.gf*8)
        u4 = deconv2d(u3, d3, self.gf*4)
        u5 = deconv2d(u4, d2, self.gf*2)
        u6 = deconv2d(u5, d1, self.gf)

        u7 = UpSampling2D(size=2)(u6)
        output_img = Conv2D(self.channels, kernel_size=4, strides=1, padding='same', activation='tanh')(u7)

        return Model(d0, output_img)

    def build_discriminator(self):

        def d_layer(layer_input, filters, f_size=4, bn=True):
            """Discriminator layer"""
            d = Conv2D(filters, kernel_size=f_size, strides=2, padding='same')(layer_input)
            d = LeakyReLU(alpha=0.2)(d)
            if bn:
                d = BatchNormalization(momentum=0.8)(d)
            return d # class 'tensorflow.python.framework.ops.Tensor'

        img_A = Input(shape=self.img_shape)
        img_B = Input(shape=self.img_shape)

        # Concatenate image and conditioning image by channels to produce input
        combined_imgs = Concatenate(axis=-1)([img_A, img_B]) #(?, 256, 256, 6)

        d1 = d_layer(combined_imgs, self.df, bn=False) # (?, 128, 128, 64)  
        d2 = d_layer(d1, self.df*2) # (?, 64, 64, 128)
        d3 = d_layer(d2, self.df*4) # (?, 32, 32, 256) 
        d4 = d_layer(d3, self.df*8) # (?, 16, 16, 512)
        
        validity = Conv2D(1, kernel_size=4, strides=1, padding='same')(d4) # (?, 16, 16, 1)

        return Model([img_A, img_B], validity)

    def train(self,dataset_train, dataset_test, epochs, batch_size=5, sample_interval=28 , total_batch=587, train_vol=1000):
        
        start_time = datetime.datetime.now()
        
        # Adversarial loss ground truths
        valid = np.ones((batch_size,) + self.disc_patch)
        fake = np.zeros((batch_size,) + self.disc_patch)
        

        for epoch in range(epochs):
            batch_i = 0
            for imgs_A, imgs_B in dataset_train:
                
                #if batch_i >= total_batch-1:
                #    break
                # ---------------------
                #  Train Discriminator
                # ---------------------

                # Condition on B and generate a translated version
                fake_A = self.generator.predict(imgs_B)

                # Train the discriminators (original images = real / generated = Fake)
                d_loss_real = self.discriminator.train_on_batch([imgs_A, imgs_B], valid)
                d_loss_fake = self.discriminator.train_on_batch([fake_A, imgs_B], fake)
                d_loss = 0.5 * np.add(d_loss_real, d_loss_fake)

                # -----------------
                #  Train Generator
                # -----------------

                # Train the generators
                g_loss = self.combined.train_on_batch([imgs_A, imgs_B], [valid, imgs_A])

                elapsed_time = datetime.datetime.now() - start_time
                # Plot the progress
                print ("[Epoch %d/%d] [Batch %d/%d] [D loss: %f, acc: %3d%%] [G loss: %f] time: %s" % (epoch, epochs,
                                                                        batch_i, total_batch,
                                                                        d_loss[0], 100*d_loss[1],
                                                                        g_loss[0],
                                                                        elapsed_time))

                # If at save interval => save generated image samples
                if batch_i % sample_interval == 0 and batch_i > 0:
                    self.sample_images(epoch, batch_i,dataset_test)
                
                batch_i = batch_i + 1
                
            #shuffle to re-train  

            dataset_train = dataset_train.shuffle(train_vol)
        '''
        # serialize model to JSON
        com_model_json = self.combined.to_json()
        gen_model_json = self.generator.to_json()
        dis_model_json = self.discriminator.to_json() 
        with open("c:\\com_model.json", "w") as json_file:
            json_file.write(com_model_json)
        with open("c:\\gen_model.json", "w") as json_file:
            json_file.write(gen_model_json)
        with open("c:\\dis_model.json", "w") as json_file:
            json_file.write(dis_model_json)	
        '''
        # serialize weights to HDF5
        self.combined.save_weights("c:\\com_model.h5")
        self.generator.save_weights("c:\\gen_model.h5")
        self.discriminator.save_weights("c:\\dis_model.h5")
        print("Model saved")

    def sample_images(self, epoch, batch_i,dataset_test):
        os.makedirs('c:\\images\\%s' % self.dataset_name, exist_ok=True)
        r, c = 3, 3

        #imgs_A, imgs_B = next(iter(dataset_test))
        stt = 0
        for imgs_A, imgs_B in dataset_test:
            
            fake_A = self.generator.predict(imgs_B)

            gen_imgs = np.concatenate([imgs_B, fake_A, imgs_A])

            # Rescale images 0 - 1
            gen_imgs = 0.5 * gen_imgs + 0.5

            titles = ['Condition', 'Generated', 'Original']
            fig, axs = plt.subplots(r, c)
            cnt = 0
            for i in range(r):
                for j in range(c):
                    axs[i,j].imshow(gen_imgs[cnt])
                    axs[i, j].set_title(titles[i])
                    axs[i,j].axis('off')
                    cnt += 1
            fig.savefig("c:\\images\\%s\\%d_%d_%d.png" % (self.dataset_name, epoch, batch_i, stt))
            plt.close()
            stt = stt + 1

'''
if __name__ == '__main__':
    gan = Pix2Pix()
    ## Train the model
    #  gan.train(epochs=80, batch_size=8, sample_interval=14)

    ## use the trained model to generate data
    test_model = gan.generator
    test_model.load_weights("./saved_models/gen_model.h5")
    path = glob("./datasets/pathology/test_random/*")
    num = 1
    for img in path:
        img_B = scipy.misc.imread(img, mode='RGB').astype(np.float)
        m,n,d = img_B.shape
        img_show = np.zeros((m,2*n,d))

        img_b = np.array([img_B])/127.5 - 1
        fake_A = 0.5* (test_model.predict(img_b))[0]+0.5
        img_show[:,:n,:] = img_B/255
        img_show[:,n:2*n,:] = fake_A
        scipy.misc.imsave("./images/pathology/test_random/%d.jpg" % num,img_show)
        num = num + 1
'''