<template>
  <v-row>
    <v-col>
      <v-card>
        <v-card-title>Overview</v-card-title>
        <v-card-text>
          <v-simple-table>
            <thead>
              <tr>
                <th class="text-left">Result</th>
                <th class="text-left">{{ currency.ticker_symbol }} value</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(item, key) in overview" :key="key">
                <td>{{ key | splitOnCapital }}</td>
                <td>
                  {{
                    item
                      | calculatePrice(exchangeRate(currency.ticker_symbol))
                      | formatPrice(floatingPrecision)
                  }}
                </td>
              </tr>
            </tbody>
          </v-simple-table>
        </v-card-text>
      </v-card>
    </v-col>
  </v-row>
</template>

<script lang="ts">
import { Component, Vue } from 'vue-property-decorator';
import { createNamespacedHelpers } from 'vuex';
import { Currency } from '@/model/currency';

const { mapGetters } = createNamespacedHelpers('session');
const { mapState: mapReportsState } = createNamespacedHelpers('reports');
const { mapGetters: mapBalanceGetters } = createNamespacedHelpers('balances');

@Component({
  computed: {
    ...mapReportsState(['overview']),
    ...mapGetters(['floatingPrecision', 'currency']),
    ...mapBalanceGetters(['exchangeRate'])
  }
})
export default class TaxReportOverview extends Vue {
  overview!: TaxReportOverview;
  currency!: Currency;
  floatingPrecision!: number;
  exchangeRate!: (currency: string) => number;
}
</script>

<style scoped></style>
